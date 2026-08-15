"""Submittal endpoints."""

from flask import Blueprint, request

import db
from errors import ApiError, ERR_SUBMITTAL_INVALID_STATE, ERR_INVALID_REQUEST
from middleware import get_user_context, require_role, get_body
from response import success_object, success_list
from services import calcs
from services.helpers import (
    base_entity, touch, paginate, get_project, get_submittal,
    req_str, req_date, opt_str, opt_enum,
)
from services.lifecycle import require_project_active, check_counterparty

bp = Blueprint("submittals", __name__)

ALL_ROLES = ("FirmAdmin", "ArchitectCA", "Contractor", "Owner")
OUTCOMES = ("APPROVED", "APPROVED_AS_NOTED", "REVISE_AND_RESUBMIT", "REJECTED")


def _late_credit_days(action_ts: str, due_at: str) -> int:
    """Whole calendar days between the date portions, floored at 0."""
    action_date = db.LogicalClock.date_of(db.LogicalClock._parse(action_ts))
    due_date = db.LogicalClock.date_of(db.LogicalClock._parse(due_at))
    delta = (db.parse_date(action_date) - db.parse_date(due_date)).days
    return max(0, delta)


@bp.post("/ca/submittals")
def create_submittal():
    user_id, role = get_user_context()
    require_role(role, ("Contractor",))
    body = get_body(required=True)
    project_id = req_str(body, "project_id")
    spec_section = req_str(body, "spec_section")
    required_on_site_date = req_date(body, "required_on_site_date")

    project = get_project(project_id)
    check_counterparty(role, user_id, project)
    require_project_active(project)

    received = db.now_iso()
    submittal = base_entity()
    submittal.update({
        "project_id": project_id,
        "spec_section": spec_section,
        "required_on_site_date": required_on_site_date,
        "revision_number": 1,
        "received_at": received,
        "due_at": db.add_days_to_dt(received, project["review_window_days_submittal"]),
        "reviewed_at": None,
        "credited_delay_days": 0,
        "review_notes": None,
        "status": "UNDER_REVIEW",
    })
    db.submittals[submittal["id"]] = submittal
    return success_object(submittal, 201)


@bp.get("/ca/submittals")
def list_submittals():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.submittals.values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [s for s in items if s["project_id"] == project_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/ca/submittals/<sid>")
def get_one_submittal(sid):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    return success_object(get_submittal(sid))


@bp.post("/ca/submittals/<sid>/review")
def review_submittal(sid):
    _, role = get_user_context()
    require_role(role, ("ArchitectCA",))
    body = get_body(required=True)
    outcome = opt_enum(body, "outcome", OUTCOMES)
    review_notes = opt_str(body, "review_notes", None)

    submittal = get_submittal(sid)
    if submittal["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_SUBMITTAL_INVALID_STATE, "submittal review requires UNDER_REVIEW", 409)

    reviewed_at = db.now_iso()
    submittal["reviewed_at"] = reviewed_at
    submittal["review_notes"] = review_notes
    submittal["status"] = outcome

    project = db.projects[submittal["project_id"]]
    if outcome in ("APPROVED", "APPROVED_AS_NOTED"):
        submittal["credited_delay_days"] = _late_credit_days(reviewed_at, submittal["due_at"])
        touch(submittal)
        # Recompute project excusable delay + posture + DRAFT invoices.
        calcs.recompute_excusable_delay(project)
        calcs.recompute_project_dependents(project, delay_changed=True)
    else:
        # REVISE_AND_RESUBMIT / REJECTED: credit 0, no project recompute.
        submittal["credited_delay_days"] = 0
        touch(submittal)
    return success_object(submittal)


@bp.post("/ca/submittals/<sid>/resubmit")
def resubmit_submittal(sid):
    user_id, role = get_user_context()
    require_role(role, ("Contractor",))
    submittal = get_submittal(sid)
    project = db.projects[submittal["project_id"]]
    check_counterparty(role, user_id, project)
    if submittal["status"] != "REVISE_AND_RESUBMIT":
        raise ApiError(ERR_SUBMITTAL_INVALID_STATE, "submittal resubmit requires REVISE_AND_RESUBMIT", 409)

    received = db.now_iso()
    submittal["revision_number"] += 1
    submittal["received_at"] = received
    submittal["due_at"] = db.add_days_to_dt(received, project["review_window_days_submittal"])
    submittal["reviewed_at"] = None
    submittal["credited_delay_days"] = 0
    submittal["status"] = "UNDER_REVIEW"
    touch(submittal)
    return success_object(submittal)


@bp.post("/ca/submittals/<sid>/vacate-review")
def vacate_submittal_review(sid):
    _, role = get_user_context()
    require_role(role, ("ArchitectCA",))
    submittal = get_submittal(sid)
    if submittal["status"] not in ("APPROVED", "APPROVED_AS_NOTED"):
        raise ApiError(
            ERR_SUBMITTAL_INVALID_STATE,
            "vacate-review requires APPROVED or APPROVED_AS_NOTED",
            409,
        )

    project = db.projects[submittal["project_id"]]
    received = db.now_iso()
    submittal["credited_delay_days"] = 0
    submittal["reviewed_at"] = None
    submittal["received_at"] = received
    submittal["due_at"] = db.add_days_to_dt(received, project["review_window_days_submittal"])
    submittal["status"] = "UNDER_REVIEW"
    touch(submittal)
    # Compensating recompute of project aggregates.
    calcs.recompute_excusable_delay(project)
    calcs.recompute_project_dependents(project, delay_changed=True)
    return success_object(submittal)
