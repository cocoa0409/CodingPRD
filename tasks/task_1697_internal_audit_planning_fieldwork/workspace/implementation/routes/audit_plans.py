"""AuditPlan endpoints (PRD 3.3): the committee approval negotiation cycle."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_PLAN_EMPTY,
    ERR_PLAN_HAS_OPEN_ENGAGEMENTS,
    ERR_PLAN_INVALID_STATE,
    ERR_PLAN_SELF_APPROVAL,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one
from services.cascades import recompute_plan_aggregates
from services.core import new_record, public, touch
from util import CLOCK
from validate import check_unknown_fields, get_body, req_int, req_str, require_path

bp = Blueprint("audit_plans", __name__)

CREATE_FIELDS = {"fiscal_year", "title"}


@bp.post("/audit/audit-plans")
def create_plan():
    authorized(["ChiefAuditExecutive"])
    body = get_body()
    check_unknown_fields(body, CREATE_FIELDS)
    fiscal_year = req_int(body, "fiscal_year")
    title = req_str(body, "title")
    rec = new_record("audit_plans", {
        "fiscal_year": fiscal_year,
        "title": title,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "submitted_at": None,
        "approved_at": None,
        "engagement_count": 0,
        "high_risk_coverage_pct": 100.0,
    })
    # Coverage is a live aggregate: with zero engagements it is 100.0 when the
    # high-risk universe is empty, else 0.0 (nothing covered yet).
    recompute_plan_aggregates(rec)
    return success_object(public(rec), status=201)


@bp.get("/audit/audit-plans/<rid>")
def get_plan(rid):
    return get_one("audit_plans", rid)


@bp.post("/audit/audit-plans/<rid>/submit")
def submit_plan(rid):
    caller = authorized(["ChiefAuditExecutive"])
    plan = require_path("audit_plans", rid)
    # Stage 7: DRAFT or RETURNED only
    if plan["status"] not in ("DRAFT", "RETURNED"):
        raise_error(ERR_PLAN_INVALID_STATE,
                    f"plan must be DRAFT or RETURNED to submit, not {plan['status']}")
    # Stage 9: zero-engagement plans cannot be submitted
    if plan["engagement_count"] < 1:
        raise_error(ERR_PLAN_EMPTY, "plan has no engagements")
    plan["status"] = "SUBMITTED"
    plan["submitted_by_user_id"] = caller.user_id
    plan["submitted_at"] = CLOCK.now_iso()
    touch(plan)
    return success_object(public(plan))


@bp.post("/audit/audit-plans/<rid>/approve")
def approve_plan(rid):
    caller = authorized(["AuditCommittee"])
    plan = require_path("audit_plans", rid)
    # Stage 7: SUBMITTED only
    if plan["status"] != "SUBMITTED":
        raise_error(ERR_PLAN_INVALID_STATE, "plan is not SUBMITTED")
    # Stage 8: segregation of duties — approver differs from submitter
    if caller.user_id == plan["submitted_by_user_id"]:
        raise_error(ERR_PLAN_SELF_APPROVAL, "approver must differ from submitter")
    plan["status"] = "APPROVED"
    plan["approved_by_user_id"] = caller.user_id
    plan["approved_at"] = CLOCK.now_iso()
    touch(plan)
    return success_object(public(plan))


@bp.post("/audit/audit-plans/<rid>/return")
def return_plan(rid):
    authorized(["AuditCommittee"])
    plan = require_path("audit_plans", rid)
    if plan["status"] != "SUBMITTED":
        raise_error(ERR_PLAN_INVALID_STATE, "plan is not SUBMITTED")
    plan["status"] = "RETURNED"
    touch(plan)
    return success_object(public(plan))


@bp.post("/audit/audit-plans/<rid>/close")
def close_plan(rid):
    authorized(["ChiefAuditExecutive"])
    plan = require_path("audit_plans", rid)
    # Stage 7: APPROVED only
    if plan["status"] != "APPROVED":
        raise_error(ERR_PLAN_INVALID_STATE, "plan is not APPROVED")
    # Stage 9: every engagement terminal
    for eng in db["engagements"].values():
        if eng["audit_plan_id"] == plan["id"] and eng["status"] not in ("CLOSED", "CANCELLED"):
            raise_error(ERR_PLAN_HAS_OPEN_ENGAGEMENTS,
                        "all engagements must be CLOSED or CANCELLED before plan close")
    plan["status"] = "CLOSED"
    touch(plan)
    return success_object(public(plan))
