"""QDRO cases, attorney authorizations, correspondence and the projection read."""
from flask import Blueprint

import auth
import enums
import errors
import services
import validation as v
from auth import endpoint
from envelope import object_response, paginate
from routes_participants import find_participant
from store import db, order_by, public, public_list
from timeutil import fmt_date, midnight, parse_date

bp = Blueprint("cases", __name__)


def find_case(case_id):
    case = db.qdro_cases.get(case_id)
    if case is None:
        errors.fail(errors.ERR_QDRO_CASE_NOT_FOUND, "No QDRO case with that id.")
    return case


def find_authorization(authorization_id):
    row = db.attorney_authorizations.get(authorization_id)
    if row is None:
        errors.fail(errors.ERR_AUTHORIZATION_NOT_FOUND, "No attorney authorization with that id.")
    return row


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap; a null end is unbounded forward."""
    if a_end is not None and b_start >= a_end:
        return False
    if b_end is not None and a_start >= b_end:
        return False
    return True


@bp.route("/qdro-cases", methods=["POST"])
@endpoint("PlanAdministrator", "QdroAnalyst")
def open_case(caller):
    data = v.body()
    participant_id = v.req_string(data, "participant_id", 1, 200)
    alternate_payee_name = v.req_string(data, "alternate_payee_name", 1, 120)
    valuation_date = v.req_date(data, "valuation_date")
    marital_period_start = v.req_date(data, "marital_period_start")
    marital_period_end = v.opt_date(data, "marital_period_end")
    alternate_payee_dob = v.opt_date(data, "alternate_payee_dob")
    address_on_file = v.opt_bool(data, "alternate_payee_address_on_file", False)
    if marital_period_end is not None and not marital_period_start < marital_period_end:
        errors.bad_request("'marital_period_start' must be strictly earlier than "
                           "'marital_period_end'.")
    participant = db.participants.get(participant_id)
    if participant is None:
        errors.fail(errors.ERR_PARTICIPANT_NOT_FOUND, "No participant with that id.")
    for other in db.qdro_cases.values():
        if other["participant_id"] != participant_id or other["review_status"] == "DENIED":
            continue
        other_end = parse_date(other["marital_period_end"]) if other["marital_period_end"] else None
        if _overlaps(marital_period_start, marital_period_end,
                     parse_date(other["marital_period_start"]), other_end):
            errors.fail(errors.ERR_MARITAL_PERIOD_OVERLAP,
                        "The marital period overlaps another live case on this participant.")
    case = db.new_row("QdroCase", {
        "participant_id": participant_id,
        "alternate_payee_name": alternate_payee_name,
        "alternate_payee_dob": fmt_date(alternate_payee_dob) if alternate_payee_dob else None,
        "alternate_payee_address_on_file": address_on_file,
        "marital_period_start": fmt_date(marital_period_start),
        "marital_period_end": fmt_date(marital_period_end) if marital_period_end else None,
        "valuation_date": fmt_date(valuation_date),
        "review_status": "INTAKE",
        "segregation_status": "NONE",
        "approach": None,
        "formula_code": None,
        "assigned_percentage_bps": None,
        "assigned_flat_amount_cents": None,
        "shared_payment_end_date": None,
    })
    db.qdro_cases[case["id"]] = case
    return object_response(public(case), 201)


@bp.route("/qdro-cases/<id>", methods=["GET"])
@endpoint("PlanAdministrator", "QdroAnalyst", "Participant", "AlternatePayee", "Attorney")
def read_case(caller, id):
    case = find_case(id)
    auth.own_case(caller, case)
    auth.attorney_standing(caller)
    return object_response(public(case))


@bp.route("/participants/<id>/qdro-cases", methods=["GET"])
@endpoint("PlanAdministrator", "QdroAnalyst", "Participant")
def list_participant_cases(caller, id):
    review_status = v.query_enum("review_status", enums.REVIEW_STATUSES)
    segregation_status = v.query_enum("segregation_status", enums.SEGREGATION_STATUSES)
    participant = find_participant(id)
    auth.own_participant(caller, participant["id"])
    rows = [r for r in db.qdro_cases.values() if r["participant_id"] == participant["id"]]
    if review_status is not None:
        rows = [r for r in rows if r["review_status"] == review_status]
    if segregation_status is not None:
        rows = [r for r in rows if r["segregation_status"] == segregation_status]
    return paginate(public_list(order_by(rows, "created_at")))


@bp.route("/qdro-cases/<id>/benefit-projection", methods=["GET"])
@endpoint("PlanAdministrator", "QdroAnalyst", "Participant", "Attorney")
def read_benefit_projection(caller, id):
    approach = v.query_enum("approach", enums.APPROACHES)
    case = find_case(id)
    auth.own_case(caller, case)
    auth.attorney_standing(caller)
    return object_response(services.benefit_projection(case, approach))


@bp.route("/qdro-cases/<id>/attorney-authorizations", methods=["POST"])
@endpoint("PlanAdministrator", "QdroAnalyst")
def record_authorization(caller, id):
    data = v.body()
    represents = v.req_enum(data, "represents", enums.REPRESENTS)
    attorney_name = v.req_string(data, "attorney_name", 1, 120)
    attorney_bar_number = v.req_string(data, "attorney_bar_number", 1, 32)
    attorney_email = v.req_string(data, "attorney_email", 1, 200)
    disclosure_scope = v.req_enum(data, "disclosure_scope", enums.DISCLOSURE_LEVELS)
    effective_from = v.req_date(data, "effective_from")
    expires_at = v.req_instant(data, "expires_at")
    if "@" not in attorney_email:
        errors.bad_request("Field 'attorney_email' must contain an at-sign.")
    if not expires_at > midnight(effective_from):
        errors.bad_request("'expires_at' must be strictly after midnight UTC on 'effective_from'.")
    case = find_case(id)
    authorization = db.new_row("AttorneyAuthorization", {
        "qdro_case_id": case["id"],
        "represents": represents,
        "attorney_name": attorney_name,
        "attorney_bar_number": attorney_bar_number,
        "attorney_email": attorney_email,
        "disclosure_scope": disclosure_scope,
        "effective_from": fmt_date(effective_from),
        "expires_at": data["expires_at"],
        "status": "ACTIVE",
        "revoked_at": None,
    })
    db.attorney_authorizations[authorization["id"]] = authorization
    db.touch(case)
    return object_response(public(authorization), 201)


@bp.route("/qdro-cases/<id>/attorney-authorizations", methods=["GET"])
@endpoint("PlanAdministrator", "QdroAnalyst", "Attorney")
def list_authorizations(caller, id):
    represents = v.query_enum("represents", enums.REPRESENTS)
    status = v.query_enum("status", enums.AUTHORIZATION_STATUSES)
    case = find_case(id)
    auth.own_case(caller, case)
    auth.attorney_standing(caller)
    rows = services.authorizations_of_case(case["id"])
    if represents is not None:
        rows = [r for r in rows if r["represents"] == represents]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(public_list(rows))


@bp.route("/attorney-authorizations/<id>/revoke", methods=["POST"])
@endpoint("PlanAdministrator")
def revoke_authorization(caller, id):
    authorization = find_authorization(id)
    if authorization["status"] != "ACTIVE":
        errors.fail(errors.ERR_AUTHORIZATION_NOT_ACTIVE,
                    "This authorization is already revoked.")
    authorization["status"] = "REVOKED"
    authorization["revoked_at"] = db.now_iso()
    db.touch(authorization)
    return object_response(public(authorization))


def _resolve_side_authorization(case_id, recipient_type):
    """The authorization representing the addressed side, ACTIVE preferred (PRD 2.11)."""
    side = "PARTICIPANT" if recipient_type == "PARTICIPANT_ATTORNEY" else "ALTERNATE_PAYEE"
    matching = [r for r in services.authorizations_of_case(case_id) if r["represents"] == side]
    if not matching:
        return None
    active = [r for r in matching if r["status"] == "ACTIVE"]
    if active:
        return active[-1]
    return matching[-1]


@bp.route("/qdro-cases/<id>/communications", methods=["POST"])
@endpoint("QdroAnalyst")
def send_communication(caller, id):
    data = v.body()
    recipient_type = v.req_enum(data, "recipient_type", enums.RECIPIENT_TYPES)
    template_code = v.req_enum(data, "template_code", enums.TEMPLATE_CODES)
    disclosure_level = v.req_enum(data, "disclosure_level", enums.DISCLOSURE_LEVELS)
    case = find_case(id)
    # Rung 11 - disclosure scope, evaluated before cross-entity readiness.
    authorization = None
    if recipient_type in ("PARTICIPANT_ATTORNEY", "AP_ATTORNEY"):
        authorization = _resolve_side_authorization(case["id"], recipient_type)
        if (authorization is not None and disclosure_level == "FULL"
                and authorization["disclosure_scope"] == "LIMITED"):
            errors.fail(errors.ERR_DISCLOSURE_SCOPE_EXCEEDED,
                        "The addressed attorney's disclosure scope is LIMITED.")
    elif recipient_type == "ALTERNATE_PAYEE":
        if disclosure_level == "FULL" and case["review_status"] != "QUALIFIED":
            errors.fail(errors.ERR_DISCLOSURE_SCOPE_EXCEEDED,
                        "Before qualification the alternate payee is entitled only to LIMITED "
                        "detail.")
    # Rung 16 - the case must have the draft order the correspondence presupposes.
    if services.operative_draft(case["id"]) is None:
        errors.fail(errors.ERR_NO_ACTIVE_DRAFT_ORDER,
                    "No draft order has ever been received on this case.")
    attorney_email = None
    if recipient_type in ("PARTICIPANT_ATTORNEY", "AP_ATTORNEY"):
        if authorization is None or authorization["status"] != "ACTIVE":
            errors.fail(errors.ERR_ATTORNEY_NOT_AUTHORIZED,
                        "No ACTIVE authorization on this case represents the addressed side.")
        attorney_email = authorization["attorney_email"]
    communication = services.append_communication(
        case, recipient_type, template_code, disclosure_level, "MANUAL", attorney_email)
    return object_response(public(communication), 201)


@bp.route("/qdro-cases/<id>/communications", methods=["GET"])
@endpoint("PlanAdministrator", "QdroAnalyst", "Participant", "AlternatePayee", "Attorney")
def list_communications(caller, id):
    recipient_type = v.query_enum("recipient_type", enums.RECIPIENT_TYPES)
    template_code = v.query_enum("template_code", enums.TEMPLATE_CODES)
    origin = v.query_enum("origin", enums.ORIGINS)
    case = find_case(id)
    auth.own_case(caller, case)
    auth.attorney_standing(caller)
    rows = services.communications_of_case(case["id"])
    if recipient_type is not None:
        rows = [r for r in rows if r["recipient_type"] == recipient_type]
    if template_code is not None:
        rows = [r for r in rows if r["template_code"] == template_code]
    if origin is not None:
        rows = [r for r in rows if r["origin"] == origin]
    return paginate(public_list(rows))


@bp.route("/qdro-cases/<id>/alternate-payee-accounts", methods=["GET"])
@endpoint("PlanAdministrator", "QdroAnalyst", "Participant", "AlternatePayee", "Attorney")
def list_case_ap_accounts(caller, id):
    case = find_case(id)
    auth.own_case(caller, case)
    auth.attorney_standing(caller)
    rows = [r for r in db.ap_accounts.values() if r["qdro_case_id"] == case["id"]]
    return paginate(public_list(order_by(rows, "created_at")))
