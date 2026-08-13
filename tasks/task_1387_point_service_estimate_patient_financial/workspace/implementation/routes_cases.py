"""Case endpoints: get/list, clear (ordered gates), cancel (cascade)."""

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_AUTH_NOT_SATISFIED,
    ERR_DEPOSIT_SHORTFALL,
    ERR_ESCALATION_PENDING,
    ERR_ESCALATION_REQUIRED,
    invalid_state,
    not_found,
)
from middleware import ALL_ROLES, authenticate
from response import ok_list, ok_object
from services import (
    cancel_case_cascade,
    case_escalations,
    case_estimates,
    recompute_case,
)
from util import paginate, serialize, touch

bp = Blueprint("cases", __name__)


def get_case_or_404(cid):
    case = db.cases.get(cid)
    if case is None:
        raise not_found("case not found")
    return case


@bp.get("/clearance/cases/<cid>")
def get_case(cid):
    authenticate(ALL_ROLES)
    case = get_case_or_404(cid)
    return ok_object(serialize(case))


@bp.get("/clearance/cases")
def list_cases():
    authenticate(ALL_ROLES)
    items = list(db.cases.values())
    patient_id = request.args.get("patient_id")
    status = request.args.get("status")
    if patient_id is not None:
        items = [c for c in items if c["patient_id"] == patient_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    return ok_list([serialize(c) for c in page], meta)


@bp.post("/clearance/cases/<cid>/clear")
def clear_case(cid):
    authenticate(["ClearanceSupervisor"])
    case = get_case_or_404(cid)
    # state legality: clear is offered from IN_REVIEW only
    if case["status"] != "IN_REVIEW":
        raise invalid_state("case is not IN_REVIEW")
    recompute_case(case)
    # gate order (PRD 2.8): auth (compliance) -> escalation required -> pending -> deposit
    if not case["auth_satisfied"]:
        raise ApiError(ERR_AUTH_NOT_SATISFIED, "case authorization requirement is not satisfied", 409)
    if case["high_dollar_flag"]:
        escs = case_escalations(case["id"])
        approved_hd = any(
            e["status"] == "APPROVED" and e["reason"] == "HIGH_DOLLAR"
            and e["estimate_id"] == case["active_estimate_id"]
            for e in escs
        )
        open_hd = any(
            e["status"] == "OPEN" and e["reason"] == "HIGH_DOLLAR"
            and e["estimate_id"] == case["active_estimate_id"]
            for e in escs
        )
        if not approved_hd and not open_hd:
            raise ApiError(ERR_ESCALATION_REQUIRED,
                           "high-dollar case has no APPROVED HIGH_DOLLAR escalation and none OPEN", 409)
    if any(e["status"] == "OPEN" for e in case_escalations(case["id"])):
        raise ApiError(ERR_ESCALATION_PENDING, "an escalation on the case is still OPEN", 409)
    if not case["deposit_satisfied"]:
        raise ApiError(ERR_DEPOSIT_SHORTFALL, "deposit_posted_cents is below required_deposit_cents", 409)
    case["status"] = "CLEARED"
    recompute_case(case)
    touch(case)
    return ok_object(serialize(case))


@bp.post("/clearance/cases/<cid>/cancel")
def cancel_case(cid):
    authenticate(["ClearanceSupervisor"])
    case = get_case_or_404(cid)
    if case["status"] not in ("OPEN", "IN_REVIEW", "CLEARED"):
        raise invalid_state("case cannot be cancelled from its current state")
    if any(e["status"] == "FINALIZED" for e in case_estimates(case["id"])):
        raise invalid_state("a case with a FINALIZED estimate cannot be cancelled")
    cancel_case_cascade(case)
    case["status"] = "CANCELLED"
    recompute_case(case)
    touch(case)
    return ok_object(serialize(case))
