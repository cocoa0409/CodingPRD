"""IhpCase endpoints — PRD §3.3, §3.4, §3.9."""
from flask import Blueprint

from db import STORE, now_dt, now_iso
from errors import ApiError
from middleware import get_auth, require_roles
from response import success
from services.common import lookup, list_response
from services.models import base_entity, touch, serialize
from services.validation import require_body, req_str, req_int
from services import case_ops, calc

bp = Blueprint("ihp_cases", __name__)

ALL_ROLES = ["ProgramAdmin", "Caseworker", "Inspector"]


@bp.route("/disaster-relief/ihp-cases", methods=["POST"])
def create_case():
    _uid, role = get_auth()
    require_roles(role, ["Caseworker"])
    body = require_body()
    applicant_id = req_str(body, "applicant_id")
    assessment_id = req_str(body, "assessment_id")
    with STORE.lock:
        applicant = lookup("applicants", applicant_id)
        assessment = lookup("assessments", assessment_id)

        # State preconditions (priority 5/6)
        if applicant["status"] != "INSPECTED":
            raise ApiError("ERR_APPLICANT_NOT_INSPECTED")
        if assessment["status"] != "VERIFIED":
            raise ApiError("ERR_ASSESSMENT_NOT_VERIFIED")

        monthly_fmr_cents = req_int(body, "monthly_fmr_cents", minimum=0)

        case = base_entity()
        case.update({
            "applicant_id": applicant_id,
            "assessment_id": assessment_id,
            "monthly_fmr_cents": monthly_fmr_cents,
            "gross_eligible_cents": 0,
            "capped_eligible_cents": 0,
            "net_eligible_cents": 0,
            "dob_offset_cents": 0,
            "total_approved_cents": 0,
            "disbursed_total_cents": 0,
            "remaining_obligation_cents": 0,
            "determined_by_caseworker_id": None,
            "pre_appeal_status": None,
            "status": "DRAFT",
        })
        STORE.ihp_cases[case["id"]] = case

        # DRAFT -> ELIGIBILITY_PENDING with provisional award (same request)
        case_ops.create_line_items(case)
        case_ops.compute_provisional(case, applicant, assessment)
        case["status"] = "ELIGIBILITY_PENDING"

        # Applicant INSPECTED -> ELIGIBILITY_PENDING
        applicant["status"] = "ELIGIBILITY_PENDING"
        touch(applicant)
        return success(serialize(case), status=201)


@bp.route("/disaster-relief/ihp-cases", methods=["GET"])
def list_cases():
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        data, pg = list_response(
            STORE.ihp_cases.values(),
            {
                "applicant_id": "applicant_id",
                "assessment_id": "assessment_id",
                "determined_by_caseworker_id": "determined_by_caseworker_id",
                "status": "status",
            },
        )
    return success(data, pagination=pg)


@bp.route("/disaster-relief/ihp-cases/<cid>", methods=["GET"])
def get_case(cid):
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        case = lookup("ihp_cases", cid)
        return success(serialize(case))


@bp.route("/disaster-relief/ihp-cases/<cid>/approve", methods=["POST"])
def approve_case(cid):
    uid, role = get_auth()
    require_roles(role, ["Caseworker"])
    with STORE.lock:
        case = lookup("ihp_cases", cid)
        if case["status"] != "ELIGIBILITY_PENDING":
            raise ApiError("ERR_CASE_NOT_PENDING")
        applicant = STORE.applicants[case["applicant_id"]]
        assessment = STORE.assessments[case["assessment_id"]]
        declaration = STORE.declarations[applicant["declaration_id"]]

        approved_at = now_dt()
        result = case_ops.compute_final_award(
            case, applicant, assessment, declaration,
            at_award=True, approved_at=approved_at,
        )
        if result["net"] <= 0:
            raise ApiError("ERR_NO_ELIGIBLE_AMOUNT")

        # Commit: line items -> APPROVED, reconcile totals
        for li in calc.case_line_items(case["id"]):
            li["li_status"] = "APPROVED"
            touch(li)
        case["total_approved_cents"] = result["total_approved"]
        case_ops.recompute_obligation(case)
        case["determined_by_caseworker_id"] = uid
        case["status"] = "AWARD_APPROVED"
        touch(case)

        applicant["status"] = "ELIGIBLE"
        touch(applicant)
        return success(serialize(case))


@bp.route("/disaster-relief/ihp-cases/<cid>/deny", methods=["POST"])
def deny_case(cid):
    uid, role = get_auth()
    require_roles(role, ["Caseworker"])
    with STORE.lock:
        case = lookup("ihp_cases", cid)
        if case["status"] != "ELIGIBILITY_PENDING":
            raise ApiError("ERR_CASE_NOT_PENDING")
        applicant = STORE.applicants[case["applicant_id"]]

        for li in calc.case_line_items(case["id"]):
            li["li_status"] = "VOIDED"
            touch(li)
        case["total_approved_cents"] = 0
        case_ops.recompute_obligation(case)
        case["determined_by_caseworker_id"] = uid
        case["status"] = "DENIED"
        touch(case)

        applicant["status"] = "INELIGIBLE"
        touch(applicant)
        return success(serialize(case))


@bp.route("/disaster-relief/ihp-cases/<cid>/close", methods=["POST"])
def close_case(cid):
    _uid, role = get_auth()
    require_roles(role, ["Caseworker", "ProgramAdmin"])
    with STORE.lock:
        case = lookup("ihp_cases", cid)
        if case["status"] != "DISBURSING":
            raise ApiError("ERR_CASE_NOT_DISBURSING")
        for r in STORE.recoupments.values():
            if r["ihp_case_id"] == cid and r["status"] == "ESTABLISHED":
                raise ApiError("ERR_OPEN_RECOUPMENT")
        case["status"] = "CLOSED"
        touch(case)
        return success(serialize(case))
