"""Enforcement cases, customs recordations, diversion investigations and the
operational enforcement sweep."""

from flask import Blueprint

import constants as C
import db
import entities
import ledger
import reps
import validation as V
from errors import fail
from middleware import (ALL_ROLES, AUTHORIZED_REPRESENTATIVE,
                        BRAND_ADMINISTRATOR, CUSTOMS_COORDINATOR,
                        ENFORCEMENT_ANALYST, LEGAL_COUNSEL,
                        MARKETPLACE_LIAISON, authenticate)
from response import created, ok, public
from timeutil import add_business_days
from versioning import touch

bp = Blueprint("legal", __name__)


# ------------------------------------------------------- enforcement cases ----

@bp.route("/brand-protection/cases", methods=["POST"])
def create_case():
    authenticate(LEGAL_COUNSEL)
    payload = V.body()
    brand_id = V.id_field(payload, "brand_id")
    seller_id = V.id_field(payload, "seller_id")
    brand = V.must_exist("brands", brand_id)
    seller = V.must_exist("sellers", seller_id)
    row = ledger.new_case(brand["id"], seller["id"], None)
    return created(public(row))


@bp.route("/brand-protection/cases/<case_id>", methods=["GET"])
def read_case(case_id):
    authenticate(ALL_ROLES)
    return ok(public(V.must_exist("cases", case_id)))


@bp.route("/brand-protection/cases", methods=["GET"])
def list_cases():
    authenticate(ALL_ROLES)
    return V.collection("cases", {
        "brand_id": None,
        "seller_id": None,
        "originating_takedown_id": None,
        "cease_desist_sent_by_rep_id": None,
        "litigation_authorized_by_rep_id": None,
        "case_status": C.CASE_STATUSES,
        "correspondence_status": C.CORRESPONDENCE_STATUSES,
        "litigation_status": C.LITIGATION_STATUSES,
    })


@bp.route("/brand-protection/cases/<case_id>/cease-desist", methods=["POST"])
def send_cease_desist(case_id):
    identity = authenticate(AUTHORIZED_REPRESENTATIVE)
    payload = V.body()
    letter_ref = V.string_field(payload, "letter_ref", 1, 80)
    case = V.must_exist("cases", case_id)
    # priority 20
    if case["case_status"] != "OPEN" or case["correspondence_status"] != "NONE":
        fail("ERR_INVALID_STATE")
    # priority 30 then 35 - any of the three scope values satisfies this action
    reps.require_effective(identity.representative)
    if identity.representative["authority_scope"] not in C.AUTHORITY_SCOPES:
        fail("ERR_REPRESENTATIVE_SCOPE_INSUFFICIENT")
    # priority 42
    seller = db.get("sellers", case["seller_id"])
    if seller is None or seller["status"] not in ("UNDER_INVESTIGATION",
                                                 "BLOCKED"):
        fail("ERR_SELLER_NOT_UNDER_INVESTIGATION")
    moment = db.now()
    case["correspondence_status"] = "CD_SENT"
    case["cease_desist_sent_by_rep_id"] = identity.user_id
    case["letter_ref"] = letter_ref
    case["cd_sent_at"] = moment
    case["cd_response_due_at"] = add_business_days(moment, C.CD_RESPONSE_DAYS)
    touch(case)
    return ok(public(case))


@bp.route("/brand-protection/cases/<case_id>/record-response", methods=["POST"])
def record_case_response(case_id):
    authenticate(LEGAL_COUNSEL)
    payload = V.body()
    V.string_field(payload, "response_ref", 1, 80)
    response_kind = V.enum_field(payload, "response_kind", C.RESPONSE_KINDS)
    case = V.must_exist("cases", case_id)
    if case["correspondence_status"] != "CD_SENT":
        fail("ERR_INVALID_STATE")
    if (case["cd_response_due_at"] is not None
            and db.now() > case["cd_response_due_at"]):
        fail("ERR_INVALID_STATE")
    case["correspondence_status"] = "CD_RESPONDED"
    case["response_kind"] = response_kind
    touch(case)
    return ok(public(case))


@bp.route("/brand-protection/cases/<case_id>/authorize-litigation",
          methods=["POST"])
def authorize_litigation(case_id):
    identity = authenticate(AUTHORIZED_REPRESENTATIVE)
    payload = V.body()
    V.string_field(payload, "authorization_ref", 1, 80)
    case = V.must_exist("cases", case_id)
    # priority 20
    if case["litigation_status"] != "NONE" or case["case_status"] != "OPEN":
        fail("ERR_INVALID_STATE")
    # priority 30
    reps.require_effective(identity.representative)
    # priority 35 - scope must carry AUTHORIZE_LITIGATION and the designation
    # must sit under an ACTIVE enrollment of this case's brand
    reps.require_scope(identity.representative, "AUTHORIZE_LITIGATION")
    enrollment = db.get("enrollments",
                        identity.representative["enrollment_id"])
    if (enrollment is None or enrollment["enrollment_status"] != "ACTIVE"
            or enrollment["brand_id"] != case["brand_id"]):
        fail("ERR_REPRESENTATIVE_SCOPE_INSUFFICIENT")
    # priority 40
    if identity.user_id == case["cease_desist_sent_by_rep_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    # priority 44
    if case["correspondence_status"] not in ("CD_RESPONDED", "CD_IGNORED"):
        fail("ERR_CEASE_DESIST_NOT_ANSWERED")
    case["litigation_status"] = "AUTHORIZED"
    case["litigation_authorized_by_rep_id"] = identity.user_id
    case["case_status"] = "IN_LITIGATION"
    touch(case)
    return ok(public(case))


@bp.route("/brand-protection/cases/<case_id>/file-suit", methods=["POST"])
def file_suit(case_id):
    authenticate(LEGAL_COUNSEL)
    payload = V.body()
    docket_ref = V.string_field(payload, "docket_ref", 1, 80)
    V.string_field(payload, "court_code", 1, 40)
    case = V.must_exist("cases", case_id)
    if case["litigation_status"] != "AUTHORIZED":
        fail("ERR_INVALID_STATE")
    case["litigation_status"] = "FILED"
    case["docket_ref"] = docket_ref
    touch(case)
    return ok(public(case))


@bp.route("/brand-protection/cases/<case_id>/close", methods=["POST"])
def close_case(case_id):
    authenticate(LEGAL_COUNSEL)
    payload = V.body()
    outcome = V.enum_field(payload, "outcome", C.CLOSURE_OUTCOMES)
    V.string_field(payload, "closure_note", 1, 200, required=False)
    case = V.must_exist("cases", case_id)
    if case["case_status"] == "CLOSED":
        fail("ERR_INVALID_STATE")
    if outcome == "NO_ACTION":
        if case["case_status"] != "OPEN" or case["litigation_status"] != "NONE":
            fail("ERR_INVALID_STATE")
    else:
        if case["litigation_status"] != "FILED":
            fail("ERR_INVALID_STATE")
        case["litigation_status"] = outcome
    case["closure_outcome"] = outcome
    case["case_status"] = "CLOSED"
    touch(case)
    return ok(public(case))


# ------------------------------------------------------ customs recordations --

@bp.route("/brand-protection/customs-recordations", methods=["POST"])
def create_recordation():
    authenticate(CUSTOMS_COORDINATOR)
    payload = V.body()
    brand_id = V.id_field(payload, "brand_id")
    registration_id = V.id_field(payload, "registration_id")
    authority = V.enum_field(payload, "customs_authority_code",
                             C.CUSTOMS_AUTHORITY_CODES)
    nice_class = V.int_field(payload, "nice_class", minimum=1, maximum=45)
    recorded_on = V.date_field(payload, "recorded_on")
    expires_on = V.date_field(payload, "expires_on")
    if expires_on < recorded_on:
        fail("ERR_INVALID_REQUEST",
             "expires_on must not fall before recorded_on.")
    brand = V.must_exist("brands", brand_id)
    registration = V.must_exist("registrations", registration_id)
    row = entities.new_recordation(brand["id"], registration["id"], authority,
                                   nice_class, recorded_on, expires_on)
    return created(public(row))


@bp.route("/brand-protection/customs-recordations/<recordation_id>",
          methods=["GET"])
def read_recordation(recordation_id):
    authenticate(ALL_ROLES)
    return ok(public(V.must_exist("recordations", recordation_id)))


@bp.route("/brand-protection/customs-recordations", methods=["GET"])
def list_recordations():
    authenticate(ALL_ROLES)
    return V.collection("recordations", {
        "brand_id": None,
        "registration_id": None,
        "customs_authority_code": C.CUSTOMS_AUTHORITY_CODES,
        "nice_class": V.INT_FILTER,
        "status": C.RECORDATION_STATUSES,
    })


@bp.route("/brand-protection/customs-recordations/<recordation_id>/record",
          methods=["POST"])
def record_recordation(recordation_id):
    authenticate(CUSTOMS_COORDINATOR)
    payload = V.body()
    number = V.string_field(payload, "recordation_number", 1, 40)
    recordation = V.must_exist("recordations", recordation_id)
    if recordation["status"] != "DRAFT":
        fail("ERR_INVALID_STATE")
    registration = db.get("registrations", recordation["registration_id"])
    if registration is None or registration["status"] != "REGISTERED":
        fail("ERR_REGISTRATION_NOT_ELIGIBLE")
    if not registration["principal_register"]:
        fail("ERR_RECORDATION_NOT_PRINCIPAL_REGISTER")
    # Closed, whole-date comparison among RECORDED rows of the same triple.
    for other in db.values("recordations"):
        if other["id"] == recordation["id"] or other["status"] != "RECORDED":
            continue
        if (other["brand_id"] != recordation["brand_id"]
                or other["customs_authority_code"] != recordation["customs_authority_code"]
                or other["nice_class"] != recordation["nice_class"]):
            continue
        if (recordation["recorded_on"] <= other["expires_on"]
                and other["recorded_on"] <= recordation["expires_on"]):
            fail("ERR_RECORDATION_WINDOW_OVERLAP")
    recordation["status"] = "RECORDED"
    recordation["recordation_number"] = number
    touch(recordation)
    return ok(public(recordation))


# --------------------------------------------------- diversion investigations --

def _lot_code_traceable(investigation):
    buy = db.get("test_buys", investigation["source_test_buy_id"])
    if buy is None or buy["status"] != "AUTHENTICATED_COUNTERFEIT":
        return False
    if buy["lot_code"] is None or buy["lot_code"] != investigation["lot_code"]:
        return False
    return True


@bp.route("/brand-protection/diversion-investigations", methods=["POST"])
def create_investigation():
    authenticate(CUSTOMS_COORDINATOR)
    payload = V.body()
    brand_id = V.id_field(payload, "brand_id")
    source_kind = V.enum_field(payload, "source_kind", C.SOURCE_KINDS)
    lot_code = V.string_field(payload, "lot_code", 1, 40)
    recordation_id = V.id_field(payload, "recordation_id", required=False)
    source_test_buy_id = V.id_field(payload, "source_test_buy_id",
                                    required=False)
    seller_id = V.id_field(payload, "seller_id", required=False)
    seizure_ref = V.string_field(payload, "seizure_ref", 1, 60, required=False)
    port_code = V.string_field(payload, "port_code", 1, 12, required=False)
    seized_qty = V.int_field(payload, "seized_qty", minimum=1, required=False)
    declared_value_cents = V.int_field(payload, "declared_value_cents",
                                       minimum=0, required=False)
    if source_kind == "BORDER_SEIZURE":
        if recordation_id is None:
            fail("ERR_INVALID_REQUEST",
                 "recordation_id is required for a BORDER_SEIZURE.")
        for name, value in (("seizure_ref", seizure_ref),
                            ("port_code", port_code),
                            ("seized_qty", seized_qty),
                            ("declared_value_cents", declared_value_cents)):
            if value is None:
                fail("ERR_INVALID_REQUEST",
                     "Field '%s' is required for a BORDER_SEIZURE." % name)
        source_test_buy_id = None
    else:
        if source_test_buy_id is None:
            fail("ERR_INVALID_REQUEST",
                 "source_test_buy_id is required for a TEST_BUY source.")
        recordation_id = None
        seizure_ref = None
        port_code = None
        seized_qty = None
        declared_value_cents = None
    brand = V.must_exist("brands", brand_id)
    recordation = None
    if recordation_id is not None:
        recordation = V.must_exist("recordations", recordation_id)
    if source_test_buy_id is not None:
        V.must_exist("test_buys", source_test_buy_id)
    if seller_id is not None:
        V.must_exist("sellers", seller_id)
    detention_notice_at = None
    response_due_at = None
    if source_kind == "BORDER_SEIZURE":
        if recordation["status"] != "RECORDED":
            fail("ERR_INVALID_STATE")
        detention_notice_at = db.now()
        response_due_at = add_business_days(detention_notice_at,
                                            C.DIVERSION_RESPONSE_DAYS)
    row = entities.new_investigation(
        brand["id"], recordation_id, source_test_buy_id, seller_id, source_kind,
        lot_code, seizure_ref, port_code, seized_qty, declared_value_cents,
        detention_notice_at, response_due_at)
    if source_kind == "TEST_BUY" and not _lot_code_traceable(row):
        del db.table("investigations")[row["id"]]
        fail("ERR_LOT_CODE_NOT_TRACEABLE")
    return created(public(row))


@bp.route("/brand-protection/diversion-investigations/<investigation_id>",
          methods=["GET"])
def read_investigation(investigation_id):
    authenticate(ALL_ROLES)
    return ok(public(V.must_exist("investigations", investigation_id)))


@bp.route("/brand-protection/diversion-investigations", methods=["GET"])
def list_investigations():
    authenticate(ALL_ROLES)
    return V.collection("investigations", {
        "brand_id": None,
        "recordation_id": None,
        "source_test_buy_id": None,
        "seller_id": None,
        "source_kind": C.SOURCE_KINDS,
        "status": C.INVESTIGATION_STATUSES,
    })


@bp.route("/brand-protection/diversion-investigations/<investigation_id>"
          "/submit-evidence", methods=["POST"])
def submit_investigation_evidence(investigation_id):
    authenticate(ENFORCEMENT_ANALYST)
    payload = V.body()
    evidence_ref = V.string_field(payload, "evidence_ref", 1, 80)
    distributor_ref = V.string_field(payload, "suspected_distributor_ref", 1, 80)
    investigation = V.must_exist("investigations", investigation_id)
    if investigation["status"] != "OPEN":
        fail("ERR_INVALID_STATE")
    if investigation["source_kind"] == "BORDER_SEIZURE":
        due = investigation["response_due_at"]
        if due is not None and db.now() > due:
            fail("ERR_SEIZURE_RESPONSE_WINDOW_EXPIRED")
    else:
        if not _lot_code_traceable(investigation):
            fail("ERR_LOT_CODE_NOT_TRACEABLE")
    investigation["status"] = "EVIDENCE_SUBMITTED"
    investigation["evidence_ref"] = evidence_ref
    investigation["suspected_distributor_ref"] = distributor_ref
    touch(investigation)
    return ok(public(investigation))


@bp.route("/brand-protection/diversion-investigations/<investigation_id>"
          "/conclude", methods=["POST"])
def conclude_investigation(investigation_id):
    authenticate(CUSTOMS_COORDINATOR)
    payload = V.body()
    outcome = V.enum_field(payload, "outcome", C.INVESTIGATION_OUTCOMES)
    findings_ref = V.string_field(payload, "findings_ref", 1, 80)
    investigation = V.must_exist("investigations", investigation_id)
    if outcome == "DIVERSION_CONFIRMED":
        if investigation["status"] != "EVIDENCE_SUBMITTED":
            fail("ERR_INVALID_STATE")
        if not investigation["seller_id"]:
            fail("ERR_INVALID_STATE")
    else:
        if investigation["status"] not in ("OPEN", "EVIDENCE_SUBMITTED"):
            fail("ERR_INVALID_STATE")
    investigation["status"] = outcome
    investigation["findings_ref"] = findings_ref
    investigation["concluded_at"] = db.now()
    touch(investigation)
    if outcome == "DIVERSION_CONFIRMED":
        ledger.attribute_strike(investigation["seller_id"],
                                investigation["brand_id"], None)
    return ok(public(investigation))


# ------------------------------------------------------- operational sweep ----

@bp.route("/brand-protection/ops/run-enforcement-sweep", methods=["POST"])
def run_enforcement_sweep():
    authenticate(MARKETPLACE_LIAISON, BRAND_ADMINISTRATOR)
    V.body()
    import sweep
    return ok(sweep.run())
