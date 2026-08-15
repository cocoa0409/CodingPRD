"""HardshipWaiver endpoints (PRD §3.7): decide, appeal, rescind."""

from flask import Blueprint, g, request

from db import ESTATE_CASES, WAIVERS, pub, touch
from errors import (
    ApiError,
    ERR_APPEAL_LIMIT_REACHED,
    ERR_HARDSHIP_CRITERIA_NOT_MET,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from util import paginate
from services import (
    HOMESTEAD_EXEMPT_CAP_CENTS,
    INCOME_LIMIT_CENTS,
    MAX_APPEALS,
    create_notice,
    hardship_reduction,
)

bp = Blueprint("waivers", __name__)


@bp.get("/recovery/waivers/<string:waiverId>")
@require_roles(*ALL_ROLES)
def get_waiver(waiverId):
    w = WAIVERS.get(waiverId)
    if w is None:
        raise ApiError(ERR_NOT_FOUND, "Hardship waiver not found", 404)
    return success_object(pub(w))


@bp.get("/recovery/waivers")
@require_roles(*ALL_ROLES)
def list_waivers():
    estate_case_id = request.args.get("estate_case_id")
    status = request.args.get("status")
    items = []
    for w in WAIVERS.values():
        if estate_case_id is not None and w["estate_case_id"] != estate_case_id:
            continue
        if status is not None and w["status"] != status:
            continue
        items.append(w)
    ordered, limit, offset = paginate(items)
    page = [pub(w) for w in ordered[offset : offset + limit]]
    return success_list(page, limit, offset, len(ordered))


@bp.post("/recovery/waivers/<string:waiverId>/approve")
@require_roles("RecoverySupervisor")
def approve_waiver(waiverId):
    w = WAIVERS.get(waiverId)
    if w is None:
        raise ApiError(ERR_NOT_FOUND, "Hardship waiver not found", 404)
    # Priority 5: segregation of duties vs the waiver's filer.
    if g.user_id == w["created_by_user_id"]:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES,
            "A supervisor cannot approve a waiver they filed",
            403,
        )
    if w["status"] != "PENDING":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Approve requires the waiver to be PENDING",
            409,
        )
    # Priority 9 (fiscal): FULL waivers must satisfy both statutory hardship
    # criteria; the boundaries are inclusive (<=).
    if w["waiver_type"] == "FULL" and (
        w["homestead_value_cents"] > HOMESTEAD_EXEMPT_CAP_CENTS
        or w["household_income_annual_cents"] > INCOME_LIMIT_CENTS
    ):
        raise ApiError(
            ERR_HARDSHIP_CRITERIA_NOT_MET,
            "FULL waiver hardship criteria are not met",
            409,
        )
    ec = ESTATE_CASES[w["estate_case_id"]]
    w["decided_reduction_cents"] = hardship_reduction(w, ec)
    w["status"] = "APPROVED"
    touch(w)
    # §3.7: approval subtracts the decided reduction from the estate's claim.
    ec["claim_outstanding_cents"] -= w["decided_reduction_cents"]
    if w["waiver_type"] == "FULL":
        ec["status"] = "WAIVED"
    elif ec["claim_outstanding_cents"] == 0:
        ec["status"] = "PAID"
    touch(ec)
    # §2.11: every waiver decision queues an ESTATE_DECISION_NOTICE.
    create_notice(ec["member_id"], None, ec["id"], "ESTATE_DECISION_NOTICE")
    return success_object(pub(w))


@bp.post("/recovery/waivers/<string:waiverId>/deny")
@require_roles("RecoverySupervisor")
def deny_waiver(waiverId):
    w = WAIVERS.get(waiverId)
    if w is None:
        raise ApiError(ERR_NOT_FOUND, "Hardship waiver not found", 404)
    if w["status"] != "PENDING":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Deny requires the waiver to be PENDING",
            409,
        )
    w["status"] = "DENIED"
    touch(w)
    # §3.7: denial queues an ESTATE_DECISION_NOTICE; nothing was granted.
    ec = ESTATE_CASES[w["estate_case_id"]]
    create_notice(ec["member_id"], None, ec["id"], "ESTATE_DECISION_NOTICE")
    return success_object(pub(w))


@bp.post("/recovery/waivers/<string:waiverId>/appeal")
@require_roles("EstateRecoveryOfficer")
def appeal_waiver(waiverId):
    w = WAIVERS.get(waiverId)
    if w is None:
        raise ApiError(ERR_NOT_FOUND, "Hardship waiver not found", 404)
    # §3.7: only DENIED is open to appeal.
    if w["status"] != "DENIED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Appeal requires the waiver to be DENIED",
            409,
        )
    # §3.7: a single appeal is permitted (MAX_APPEALS = 1).
    if w["appeal_count"] >= MAX_APPEALS:
        raise ApiError(
            ERR_APPEAL_LIMIT_REACHED,
            "The appeal limit for this waiver has been reached",
            409,
        )
    w["status"] = "PENDING"
    w["appeal_count"] += 1
    touch(w)
    return success_object(pub(w))


@bp.post("/recovery/waivers/<string:waiverId>/rescind")
@require_roles("RecoverySupervisor")
def rescind_waiver(waiverId):
    w = WAIVERS.get(waiverId)
    if w is None:
        raise ApiError(ERR_NOT_FOUND, "Hardship waiver not found", 404)
    if w["status"] != "APPROVED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "Rescind requires the waiver to be APPROVED",
            409,
        )
    w["status"] = "RESCINDED"
    touch(w)
    # §3.7: rescission restores the claim by the decided reduction; a WAIVED
    # estate returns to CLAIM_FILED.
    ec = ESTATE_CASES[w["estate_case_id"]]
    ec["claim_outstanding_cents"] += w["decided_reduction_cents"]
    if ec["status"] == "WAIVED":
        ec["status"] = "CLAIM_FILED"
    touch(ec)
    return success_object(pub(w))
