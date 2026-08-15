"""ActionPlan endpoints (PRD 3.7): remediation lifecycle with the
validation-failure rework loop; due-date futurity is clock-gated."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_ACTION_PLAN_INVALID_STATE,
    ERR_DUE_DATE_NOT_FUTURE,
    ERR_FINDING_INVALID_STATE,
    ERR_FINDING_NOT_AGREED,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, query_str
from services.cascades import recompute_finding_overdue
from services.core import new_record, public, touch
from util import CLOCK, parse_dt
from validate import (
    body_ref,
    check_unknown_fields,
    get_body,
    req_datetime,
    req_str,
    require_path,
)

bp = Blueprint("action_plans", __name__)

CREATE_FIELDS = {"finding_id", "description", "owner_name", "due_date"}
REJECT_FIELDS = {"rejection_note"}


@bp.post("/audit/action-plans")
def create_action_plan():
    authorized(["ManagementOwner"])
    body = get_body()
    # Stage 4: body FK existence
    body_ref(body, "finding_id", "findings")
    # Stage 5: shape
    check_unknown_fields(body, CREATE_FIELDS)
    finding_id = req_str(body, "finding_id")
    description = req_str(body, "description")
    owner_name = req_str(body, "owner_name")
    due_date = req_datetime(body, "due_date")
    # Stage 10: due_date strictly after the logical clock's current instant
    if not parse_dt(due_date) > CLOCK.now():
        raise_error(ERR_DUE_DATE_NOT_FUTURE,
                    "due_date must be strictly after the logical clock")
    # Stage 11: finding must be UNDER_REVIEW or AGREED
    finding = db["findings"][finding_id]
    if finding["status"] not in ("UNDER_REVIEW", "AGREED"):
        raise_error(ERR_FINDING_INVALID_STATE,
                    f"action plans require a finding in UNDER_REVIEW or AGREED, not {finding['status']}")
    rec = new_record("action_plans", {
        "finding_id": finding_id,
        "description": description,
        "owner_name": owner_name,
        "original_due_date": due_date,  # immutable copy — extensions never touch it
        "due_date": due_date,
        "extension_count": 0,
        "cumulative_extended_days": 0,
        "status": "OPEN",
        "validated_by_user_id": None,
        "validated_at": None,
    })
    recompute_finding_overdue(finding)
    touch(finding)
    return success_object(public(rec), status=201)


@bp.get("/audit/action-plans")
def list_action_plans():
    filters = {
        "finding_id": query_str("finding_id"),
        "status": query_str("status"),
    }
    return list_response("action_plans", filters)


@bp.get("/audit/action-plans/<rid>")
def get_action_plan(rid):
    return get_one("action_plans", rid)


@bp.post("/audit/action-plans/<rid>/start")
def start_action_plan(rid):
    authorized(["ManagementOwner"])
    plan = require_path("action_plans", rid)
    # Stage 7: must be OPEN
    if plan["status"] != "OPEN":
        raise_error(ERR_ACTION_PLAN_INVALID_STATE, "action plan is not OPEN")
    # Stage 11: cross-entity gate — finding must be AGREED
    finding = db["findings"][plan["finding_id"]]
    if finding["status"] != "AGREED":
        raise_error(ERR_FINDING_NOT_AGREED, "finding is not AGREED")
    plan["status"] = "IN_PROGRESS"
    touch(plan)
    return success_object(public(plan))


@bp.post("/audit/action-plans/<rid>/submit-validation")
def submit_validation(rid):
    authorized(["ManagementOwner"])
    plan = require_path("action_plans", rid)
    if plan["status"] != "IN_PROGRESS":
        raise_error(ERR_ACTION_PLAN_INVALID_STATE, "action plan is not IN_PROGRESS")
    plan["status"] = "SUBMITTED_FOR_VALIDATION"
    touch(plan)
    return success_object(public(plan))


@bp.post("/audit/action-plans/<rid>/validate")
def validate_action_plan(rid):
    caller = authorized(["AuditManager"])
    plan = require_path("action_plans", rid)
    if plan["status"] != "SUBMITTED_FOR_VALIDATION":
        raise_error(ERR_ACTION_PLAN_INVALID_STATE,
                    "action plan is not SUBMITTED_FOR_VALIDATION")
    plan["status"] = "VALIDATED"
    plan["validated_by_user_id"] = caller.user_id
    plan["validated_at"] = CLOCK.now_iso()
    touch(plan)
    # Ledger sync on the parent finding
    finding = db["findings"][plan["finding_id"]]
    recompute_finding_overdue(finding)
    touch(finding)
    return success_object(public(plan))


@bp.post("/audit/action-plans/<rid>/reject-validation")
def reject_validation(rid):
    authorized(["AuditManager"])
    plan = require_path("action_plans", rid)
    # Stage 5: shape (rejection_note required)
    body = get_body()
    check_unknown_fields(body, REJECT_FIELDS)
    req_str(body, "rejection_note")
    if plan["status"] != "SUBMITTED_FOR_VALIDATION":
        raise_error(ERR_ACTION_PLAN_INVALID_STATE,
                    "action plan is not SUBMITTED_FOR_VALIDATION")
    # Validation-failure loop: back to IN_PROGRESS for rework
    plan["status"] = "IN_PROGRESS"
    touch(plan)
    return success_object(public(plan))
