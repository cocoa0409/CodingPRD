"""ExtensionRequest endpoints (PRD 3.7): due-date extensions with strict
monotonicity, the 2-approval cap, the inclusive 180-day cumulative cap, and
single-PENDING uniqueness. Approval re-validates every creation-time constraint
against current data before mutating, then cascades to the finding's overdue
count."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_ACTION_PLAN_INVALID_STATE,
    ERR_EXTENSION_ALREADY_PENDING,
    ERR_EXTENSION_COUNT_EXCEEDED,
    ERR_EXTENSION_CUMULATIVE_CAP_EXCEEDED,
    ERR_EXTENSION_INVALID_STATE,
    ERR_EXTENSION_NOT_MONOTONIC,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, query_str
from services.calculations import MAX_CUMULATIVE_EXTENSION_DAYS, MAX_EXTENSIONS_PER_PLAN
from services.cascades import recompute_finding_overdue
from services.core import new_record, public, touch
from util import days_shift, parse_dt
from validate import (
    body_ref,
    check_unknown_fields,
    get_body,
    req_datetime,
    req_str,
    require_path,
)

bp = Blueprint("extension_requests", __name__)

CREATE_FIELDS = {"action_plan_id", "requested_due_date", "reason"}
EXTENDABLE_STATUSES = ("OPEN", "IN_PROGRESS")


def _validate_extension_against_plan(requested_due_date, plan):
    """Monotonicity, count cap, and inclusive cumulative cap — in the PRD's
    stated order. Used at creation and re-run at approval time."""
    requested_dt = parse_dt(requested_due_date)
    due_dt = parse_dt(plan["due_date"])
    if not requested_dt > due_dt:
        raise_error(ERR_EXTENSION_NOT_MONOTONIC,
                    "requested_due_date must be strictly after the current due_date")
    if plan["extension_count"] >= MAX_EXTENSIONS_PER_PLAN:
        raise_error(ERR_EXTENSION_COUNT_EXCEEDED,
                    "extension_count cap of 2 reached")
    shift = days_shift(plan["due_date"], requested_due_date)
    if plan["cumulative_extended_days"] + shift > MAX_CUMULATIVE_EXTENSION_DAYS:
        raise_error(ERR_EXTENSION_CUMULATIVE_CAP_EXCEEDED,
                    "cumulative extended days would exceed 180 (180 itself is allowed)")
    return shift


@bp.post("/audit/extension-requests")
def create_extension_request():
    authorized(["ManagementOwner"])
    body = get_body()
    # Stage 4: body FK existence
    body_ref(body, "action_plan_id", "action_plans")
    # Stage 5: shape
    check_unknown_fields(body, CREATE_FIELDS)
    action_plan_id = req_str(body, "action_plan_id")
    requested_due_date = req_datetime(body, "requested_due_date")
    reason = req_str(body, "reason")
    plan = db["action_plans"][action_plan_id]
    # Stage 7: plan must be OPEN or IN_PROGRESS
    if plan["status"] not in EXTENDABLE_STATUSES:
        raise_error(ERR_ACTION_PLAN_INVALID_STATE,
                    f"extensions require OPEN or IN_PROGRESS, not {plan['status']}")
    # Temporal and cap gates (PRD 3.7 creation order)
    _validate_extension_against_plan(requested_due_date, plan)
    # Finally: only one PENDING request in flight per plan
    for ext in db["extension_requests"].values():
        if ext["action_plan_id"] == action_plan_id and ext["status"] == "PENDING":
            raise_error(ERR_EXTENSION_ALREADY_PENDING,
                        "a PENDING extension request already exists for this plan")
    rec = new_record("extension_requests", {
        "action_plan_id": action_plan_id,
        "requested_due_date": requested_due_date,
        "reason": reason,
        "status": "PENDING",
        "decided_by_user_id": None,
        "approved_days": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/audit/extension-requests")
def list_extension_requests():
    filters = {
        "action_plan_id": query_str("action_plan_id"),
        "status": query_str("status"),
    }
    return list_response("extension_requests", filters)


@bp.get("/audit/extension-requests/<rid>")
def get_extension_request(rid):
    return get_one("extension_requests", rid)


@bp.post("/audit/extension-requests/<rid>/approve")
def approve_extension_request(rid):
    caller = authorized(["ChiefAuditExecutive"])
    ext = require_path("extension_requests", rid)
    # Stage 7: must be PENDING
    if ext["status"] != "PENDING":
        raise_error(ERR_EXTENSION_INVALID_STATE, "extension request is not PENDING")
    plan = db["action_plans"][ext["action_plan_id"]]
    # Re-validate the creation-time constraints against current data
    shift = _validate_extension_against_plan(ext["requested_due_date"], plan)
    ext["status"] = "APPROVED"
    ext["decided_by_user_id"] = caller.user_id
    ext["approved_days"] = shift
    touch(ext)
    # Cascade L1: mutate the action plan
    plan["due_date"] = ext["requested_due_date"]
    plan["extension_count"] = plan["extension_count"] + 1
    plan["cumulative_extended_days"] = plan["cumulative_extended_days"] + shift
    touch(plan)
    # Cascade L2: the due-date mutation re-evaluates the finding's overdue count
    finding = db["findings"][plan["finding_id"]]
    recompute_finding_overdue(finding)
    touch(finding)
    return success_object(public(ext))


@bp.post("/audit/extension-requests/<rid>/deny")
def deny_extension_request(rid):
    caller = authorized(["ChiefAuditExecutive"])
    ext = require_path("extension_requests", rid)
    if ext["status"] != "PENDING":
        raise_error(ERR_EXTENSION_INVALID_STATE, "extension request is not PENDING")
    ext["status"] = "DENIED"
    ext["decided_by_user_id"] = caller.user_id
    touch(ext)
    return success_object(public(ext))
