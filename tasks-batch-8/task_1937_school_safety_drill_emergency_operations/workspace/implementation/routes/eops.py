"""EmergencyOperationsPlan endpoints (PRD 3.3)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_SITE_PLAN_REQUIRED,
    ERR_WALKTHROUGH_REQUIRED, ERR_VALIDATION,
)
from middleware import authorized, ALL_ROLES, ROLE_COORDINATOR, ROLE_OFFICER
from response import success_object
from services.core import new_record, public, apply_changes
from util import CLOCK, days_before, parse_date
from validate import get_body, reject_unknown, req_date, req_enum, req_str, opt_str
from routes.helpers import check_site_fk, get_path, list_query

bp = Blueprint("eops", __name__)

WALKTHROUGH_WINDOW_DAYS = 365


@bp.post("/emergency-operations-plans")
def create_eop():
    authorized([ROLE_OFFICER])
    body = get_body()
    check_site_fk(body)
    reject_unknown(body, ["site_id", "title", "plan_version_label",
                          "content_summary", "review_due_date"])
    site_id = req_str(body, "site_id")
    title = req_str(body, "title")
    label = req_str(body, "plan_version_label")
    summary = req_str(body, "content_summary")
    review_due = req_date(body, "review_due_date")
    rec = new_record("eops", {
        "site_id": site_id,
        "title": title,
        "plan_version_label": label,
        "content_summary": summary,
        "review_due_date": review_due,
        "status": "DRAFT",
        "submitted_by_user_id": None,
        "return_reason": None,
        "activated_at": None,
    })
    return success_object(public(rec), 201)


@bp.get("/sites/<rid>/emergency-operations-plans")
def list_eops(rid):
    authorized(ALL_ROLES)
    get_path("sites", rid)
    filters = {"site_id": rid, "status": request.args.get("status")}
    return list_query("eops", filters)


@bp.post("/emergency-operations-plans/<rid>/submit")
def submit_eop(rid):
    caller = authorized([ROLE_OFFICER])
    plan = get_path("eops", rid)
    body = get_body()
    reject_unknown(body, [])

    if plan["status"] not in ("DRAFT", "RETURNED"):
        raise_error(ERR_INVALID_STATE, "plan must be DRAFT or RETURNED to submit")

    # priority 8a: site-plan currency
    has_current_doc = any(
        d["site_id"] == plan["site_id"] and d["status"] == "CURRENT"
        for d in db["site_plan_documents"].values()
    )
    if not has_current_doc:
        raise_error(ERR_SITE_PLAN_REQUIRED,
                    "site has no CURRENT SitePlanDocument")

    # priority 8b: walkthrough currency (trailing 365 days, inclusive boundary)
    window_start = days_before(CLOCK.today(), WALKTHROUGH_WINDOW_DAYS)
    eligible = any(
        w["site_id"] == plan["site_id"]
        and w["status"] == "COMPLETED"
        and w["completed_date"] is not None
        and parse_date(w["completed_date"]) >= window_start
        for w in db["walkthroughs"].values()
    )
    if not eligible:
        raise_error(ERR_WALKTHROUGH_REQUIRED,
                    "site has no COMPLETED walkthrough within the trailing 365 days")

    apply_changes(plan, {
        "status": "SUBMITTED",
        "submitted_by_user_id": caller.user_id,
        "return_reason": None,
    })
    return success_object(public(plan))


@bp.post("/emergency-operations-plans/<rid>/decide")
def decide_eop(rid):
    authorized([ROLE_COORDINATOR])
    plan = get_path("eops", rid)
    body = get_body()
    reject_unknown(body, ["decision", "return_reason"])
    decision = req_enum(body, "decision", ["APPROVE", "RETURN"])
    return_reason = opt_str(body, "return_reason")
    if decision == "RETURN" and (return_reason is None or return_reason.strip() == ""):
        raise_error(ERR_VALIDATION, "return_reason is required when decision is RETURN")

    if plan["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, "plan must be SUBMITTED to decide")

    if decision == "APPROVE":
        apply_changes(plan, {"status": "APPROVED"})
    else:
        apply_changes(plan, {"status": "RETURNED", "return_reason": return_reason})
    return success_object(public(plan))


@bp.post("/emergency-operations-plans/<rid>/activate")
def activate_eop(rid):
    authorized([ROLE_COORDINATOR])
    plan = get_path("eops", rid)
    body = get_body()
    reject_unknown(body, [])

    if plan["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE, "plan must be APPROVED to activate")

    # Cascade: any other ACTIVE plan at the same site -> SUPERSEDED
    for other in db["eops"].values():
        if (other["id"] != plan["id"] and other["site_id"] == plan["site_id"]
                and other["status"] == "ACTIVE"):
            apply_changes(other, {"status": "SUPERSEDED"})

    apply_changes(plan, {"status": "ACTIVE", "activated_at": CLOCK.now_iso()})
    return success_object(public(plan))
