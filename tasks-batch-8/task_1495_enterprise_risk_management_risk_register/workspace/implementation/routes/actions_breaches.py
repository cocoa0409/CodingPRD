"""Treatment actions (PRD 3.5) and tolerance breaches (PRD 3.4)."""
from flask import Blueprint

from db import store, clock_now
from errors import ApiError
from middleware import authenticate, ALL_ROLES
from response import ok_object
from services import (touch, serialize_action, serialize_breach, rollup_progress,
                      lazy_breach_sweep)
from util import json_body, req_str, req_dt

bp = Blueprint("actions_breaches", __name__)


@bp.post("/treatment-actions/<aid>/done")
def complete_action(aid):
    uid = authenticate(("RiskOwner",))
    a = store["actions"].get(aid)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Treatment action not found")
    plan = store["plans"].get(a["plan_id"])
    if plan is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Treatment plan not found")
    # ownership (priority 5) precedes state guards (priority 7)
    if plan["owner_user_id"] != uid:
        raise ApiError("ERR_OWNER_MISMATCH", 403,
                       "X-User-ID does not match the plan's owner_user_id")
    if plan["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Actions can be completed only while the plan is IN_PROGRESS")
    if a["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Action in status %s cannot be marked done" % a["status"])
    a["status"] = "DONE"
    touch(a)
    rollup_progress(plan)
    return ok_object(serialize_action(a))


# ---------------------------------------------------------------------------
# Tolerance breaches
# ---------------------------------------------------------------------------

def get_breach_or_404(bid):
    b = store["breaches"].get(bid)
    if b is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Tolerance breach not found")
    return b


def check_breach_owner(breach, uid):
    risk = store["risks"].get(breach["risk_id"])
    if risk is None or risk["owner_user_id"] != uid:
        raise ApiError("ERR_OWNER_MISMATCH", 403,
                       "X-User-ID does not match the breached risk's owner_user_id")


@bp.get("/tolerance-breaches/<bid>")
def get_breach(bid):
    authenticate(ALL_ROLES)
    b = get_breach_or_404(bid)
    lazy_breach_sweep(b)  # PRD 2.4: reading a breach re-evaluates review expiry
    return ok_object(serialize_breach(b))


@bp.post("/tolerance-breaches/<bid>/acknowledge")
def acknowledge_breach(bid):
    uid = authenticate(("RiskOwner",))
    b = get_breach_or_404(bid)
    check_breach_owner(b, uid)
    if b["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Breach in status %s cannot be acknowledged" % b["status"])
    b["status"] = "ACKNOWLEDGED"
    touch(b)
    return ok_object(serialize_breach(b))


@bp.post("/tolerance-breaches/<bid>/resolve")
def resolve_breach(bid):
    uid = authenticate(("RiskOwner",))
    b = get_breach_or_404(bid)
    check_breach_owner(b, uid)
    if b["status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Breach in status %s cannot be resolved" % b["status"])
    risk = store["risks"].get(b["risk_id"])
    stmt = store["appetite_statements"].get(b["appetite_statement_id"])
    if (risk is None or stmt is None or risk["residual_score"] is None
            or risk["residual_score"] >= stmt["tolerance_score"]):
        raise ApiError("ERR_BREACH_RESOLUTION_PREMATURE", 409,
                       "Residual score must be strictly below the tolerance to resolve")
    b["status"] = "RESOLVED"
    touch(b)
    return ok_object(serialize_breach(b))


@bp.post("/tolerance-breaches/<bid>/accept")
def accept_breach(bid):
    authenticate(("RiskManager",))
    data = json_body()
    rationale = req_str(data, "rationale")
    if not rationale.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "rationale must be non-empty")
    review_by = req_dt(data, "review_by")
    b = get_breach_or_404(bid)
    if b["status"] != "ACKNOWLEDGED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Breach in status %s cannot be accepted" % b["status"])
    risk = store["risks"].get(b["risk_id"])
    stmt = store["appetite_statements"].get(b["appetite_statement_id"])
    if (risk is None or stmt is None or risk["residual_score"] is None
            or risk["residual_score"] > stmt["acceptance_cap_score"]):
        raise ApiError("ERR_ACCEPTANCE_CAP_EXCEEDED", 422,
                       "Residual score exceeds the statement's acceptance cap")
    if not review_by > clock_now():
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "review_by must be after the current logical clock")
    b["status"] = "ACCEPTED"
    b["rationale"] = rationale
    b["review_by"] = review_by
    touch(b)
    return ok_object(serialize_breach(b))
