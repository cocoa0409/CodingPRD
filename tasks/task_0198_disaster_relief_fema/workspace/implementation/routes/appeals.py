"""Appeal endpoints — PRD §3.10."""
from flask import Blueprint

from db import STORE
from errors import ApiError
from middleware import get_auth, require_roles
from response import success
from services.common import lookup, list_response
from services.models import base_entity, touch, serialize
from services.validation import require_body, req_str, req_int, opt_int
from services import case_ops, calc

bp = Blueprint("appeals", __name__)

ALL_ROLES = ["ProgramAdmin", "Caseworker", "Inspector"]


@bp.route("/disaster-relief/appeals", methods=["POST"])
def create_appeal():
    _uid, role = get_auth()
    require_roles(role, ["Caseworker", "ProgramAdmin"])
    body = require_body()
    ihp_case_id = req_str(body, "ihp_case_id")
    with STORE.lock:
        case = lookup("ihp_cases", ihp_case_id)

        # State precondition (priority 5): case AWARD_APPROVED or DENIED
        if case["status"] not in ("AWARD_APPROVED", "DENIED"):
            raise ApiError("ERR_CASE_NOT_APPEALABLE")

        # OCC (priority 10): expected_ihp_case_version must match
        expected = req_int(body, "expected_ihp_case_version")
        if expected != case["version"]:
            raise ApiError("ERR_STALE_CASE_VERSION")

        reason = req_str(body, "reason")
        requested_repair_cost_cents = opt_int(body, "requested_repair_cost_cents", default=None, minimum=0)

        appeal = base_entity()
        appeal.update({
            "ihp_case_id": ihp_case_id,
            "expected_ihp_case_version": expected,
            "reason": reason,
            "requested_repair_cost_cents": requested_repair_cost_cents,
            "decided_by_caseworker_id": None,
            "status": "SUBMITTED",
        })
        STORE.appeals[appeal["id"]] = appeal

        # Case -> UNDER_APPEAL, record pre_appeal_status, bump version
        case["pre_appeal_status"] = case["status"]
        case["status"] = "UNDER_APPEAL"
        touch(case)
        return success(serialize(appeal), status=201)


@bp.route("/disaster-relief/appeals", methods=["GET"])
def list_appeals():
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        data, pg = list_response(
            STORE.appeals.values(),
            {"ihp_case_id": "ihp_case_id", "decided_by_caseworker_id": "decided_by_caseworker_id",
             "status": "status"},
        )
    return success(data, pagination=pg)


@bp.route("/disaster-relief/appeals/<aid>", methods=["GET"])
def get_appeal(aid):
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        a = lookup("appeals", aid)
        return success(serialize(a))


@bp.route("/disaster-relief/appeals/<aid>/decide", methods=["POST"])
def decide_appeal(aid):
    uid, role = get_auth()
    require_roles(role, ["Caseworker"])
    body = require_body()
    with STORE.lock:
        appeal = lookup("appeals", aid)
        case = STORE.ihp_cases.get(appeal["ihp_case_id"])

        # State preconditions (priority 5)
        if case is None or case["status"] != "UNDER_APPEAL":
            raise ApiError("ERR_CASE_NOT_UNDER_APPEAL")
        if appeal["status"] != "SUBMITTED":
            raise ApiError("ERR_APPEAL_NOT_SUBMITTED")

        # Segregation of duties (priority 8): decider != determiner
        if uid == case.get("determined_by_caseworker_id"):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

        # Outcome validation (priority 13)
        outcome = body.get("outcome")
        if outcome not in ("GRANTED", "DENIED"):
            raise ApiError("ERR_INVALID_APPEAL_OUTCOME", "outcome must be GRANTED or DENIED.")

        appeal["decided_by_caseworker_id"] = uid

        if outcome == "GRANTED":
            appeal["status"] = "GRANTED"
            touch(appeal)

            applicant = STORE.applicants[case["applicant_id"]]
            assessment = case_ops.case_assessment(case)
            declaration = case_ops.case_declaration(case)
            override = appeal.get("requested_repair_cost_cents")

            result = case_ops.compute_final_award(
                case, applicant, assessment, declaration,
                at_award=False, repair_override=override,
            )
            # Re-approve line items through the waterfall
            for li in calc.case_line_items(case["id"]):
                li["li_status"] = "APPROVED"
                touch(li)
            case["total_approved_cents"] = result["total_approved"]
            case_ops.recompute_obligation(case)
            case["status"] = "AWARD_APPROVED"
            case["pre_appeal_status"] = None
            touch(case)

            # APPEAL_REDUCTION recoupment if net < disbursed
            if case["net_eligible_cents"] < case["disbursed_total_cents"]:
                case_ops.maybe_establish_recoupment(case, "APPEAL_REDUCTION")
        else:
            # DENIED: restore to pre_appeal_status, no award change
            appeal["status"] = "DENIED"
            touch(appeal)
            case["status"] = case["pre_appeal_status"]
            case["pre_appeal_status"] = None
            touch(case)

        return success(serialize(appeal))
