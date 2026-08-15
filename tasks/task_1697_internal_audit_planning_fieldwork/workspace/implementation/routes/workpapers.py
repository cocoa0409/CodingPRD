"""Workpaper endpoints (PRD 3.5): the DRAFT -> SUBMITTED -> SIGNED_OFF review
pipeline with the RETURNED -> DRAFT revision loop, preparer ownership, reviewer
segregation of duties, and the last-in-pipeline fiscal budget gate."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_BUDGET_HOURS_EXCEEDED,
    ERR_ENGAGEMENT_INVALID_STATE,
    ERR_NOT_WORKPAPER_PREPARER,
    ERR_PREPARER_NOT_ASSIGNED,
    ERR_WORKPAPER_INVALID_STATE,
    ERR_WORKPAPER_LOCKED,
    ERR_WORKPAPER_SELF_REVIEW,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, query_str
from services.calculations import signoff_would_exceed_budget
from services.cascades import recompute_engagement_hours
from services.core import new_record, public, touch
from util import CLOCK
from validate import (
    body_ref,
    check_unknown_fields,
    get_body,
    req_number,
    req_str,
    require_path,
)

bp = Blueprint("workpapers", __name__)

CREATE_FIELDS = {"engagement_id", "reference", "title", "hours_worked"}
RETURN_FIELDS = {"note"}


def _require_fieldwork_engagement(wp):
    """Cross-entity gate (stage 7): all workpaper review mutations require the
    engagement to be in FIELDWORK."""
    eng = db["engagements"][wp["engagement_id"]]
    if eng["status"] != "FIELDWORK":
        raise_error(ERR_ENGAGEMENT_INVALID_STATE,
                    f"workpaper mutations require FIELDWORK, not {eng['status']}")
    return eng


def _check_unlocked(wp):
    if wp["locked"]:
        raise_error(ERR_WORKPAPER_LOCKED, "workpaper is locked by an issued report")


@bp.post("/audit/workpapers")
def create_workpaper():
    caller = authorized(["FieldAuditor"])
    body = get_body()
    # Stage 4: body FK existence
    body_ref(body, "engagement_id", "engagements")
    # Stage 5: shape
    check_unknown_fields(body, CREATE_FIELDS)
    engagement_id = req_str(body, "engagement_id")
    reference = req_str(body, "reference")
    title = req_str(body, "title")
    hours_worked = req_number(body, "hours_worked", positive=True)
    eng = db["engagements"][engagement_id]
    # Stage 7: engagement must be in FIELDWORK
    if eng["status"] != "FIELDWORK":
        raise_error(ERR_ENGAGEMENT_INVALID_STATE,
                    f"workpapers can only be created in FIELDWORK, not {eng['status']}")
    # Stage 11: the preparer must hold an ACTIVE assignment on the engagement
    assigned = any(
        a["engagement_id"] == engagement_id and a["auditor_id"] == caller.user_id
        and a["status"] == "ACTIVE"
        for a in db["engagement_assignments"].values()
    )
    if not assigned:
        raise_error(ERR_PREPARER_NOT_ASSIGNED,
                    "preparer holds no ACTIVE assignment on the engagement")
    rec = new_record("workpapers", {
        "engagement_id": engagement_id,
        "reference": reference,
        "title": title,
        "preparer_auditor_id": caller.user_id,
        "reviewer_auditor_id": None,
        "hours_worked": hours_worked,
        "status": "DRAFT",
        "review_note": None,
        "signed_off_at": None,
        "locked": False,
    })
    # DRAFT workpapers are excluded from both rollups — no ledger movement.
    return success_object(public(rec), status=201)


@bp.get("/audit/workpapers")
def list_workpapers():
    filters = {
        "engagement_id": query_str("engagement_id"),
        "preparer_auditor_id": query_str("preparer_auditor_id"),
        "reviewer_auditor_id": query_str("reviewer_auditor_id"),
        "status": query_str("status"),
    }
    return list_response("workpapers", filters)


@bp.get("/audit/workpapers/<rid>")
def get_workpaper(rid):
    return get_one("workpapers", rid)


@bp.post("/audit/workpapers/<rid>/submit")
def submit_workpaper(rid):
    caller = authorized(["FieldAuditor"])
    wp = require_path("workpapers", rid)
    # Stage 7: from-state, lock, engagement gate
    if wp["status"] != "DRAFT":
        raise_error(ERR_WORKPAPER_INVALID_STATE, "workpaper is not DRAFT")
    _check_unlocked(wp)
    eng = _require_fieldwork_engagement(wp)
    # Stage 8: ownership — only the preparer may submit
    if caller.user_id != wp["preparer_auditor_id"]:
        raise_error(ERR_NOT_WORKPAPER_PREPARER, "only the preparer may submit")
    wp["status"] = "SUBMITTED"
    touch(wp)
    recompute_engagement_hours(eng)
    touch(eng)
    return success_object(public(wp))


@bp.post("/audit/workpapers/<rid>/sign-off")
def sign_off_workpaper(rid):
    caller = authorized(["AuditManager"])
    wp = require_path("workpapers", rid)
    # Stage 7: from-state, lock, engagement gate
    if wp["status"] != "SUBMITTED":
        raise_error(ERR_WORKPAPER_INVALID_STATE, "workpaper is not SUBMITTED")
    _check_unlocked(wp)
    eng = _require_fieldwork_engagement(wp)
    # Stage 8: segregation of duties — reviewer differs from preparer
    if caller.user_id == wp["preparer_auditor_id"]:
        raise_error(ERR_WORKPAPER_SELF_REVIEW, "preparer cannot sign off own workpaper")
    # Stage 12: fiscal gate, evaluated last — after SoD
    if signoff_would_exceed_budget(eng, wp):
        raise_error(ERR_BUDGET_HOURS_EXCEEDED,
                    "sign-off would push actual_hours beyond 110% of budget_hours")
    wp["status"] = "SIGNED_OFF"
    wp["reviewer_auditor_id"] = caller.user_id
    wp["signed_off_at"] = CLOCK.now_iso()
    touch(wp)
    recompute_engagement_hours(eng)
    touch(eng)
    return success_object(public(wp))


@bp.post("/audit/workpapers/<rid>/return")
def return_workpaper(rid):
    caller = authorized(["AuditManager"])
    wp = require_path("workpapers", rid)
    # Stage 5: shape (note required)
    body = get_body()
    check_unknown_fields(body, RETURN_FIELDS)
    note = req_str(body, "note")
    # Stage 7: from-state SUBMITTED or SIGNED_OFF, lock, engagement gate
    if wp["status"] not in ("SUBMITTED", "SIGNED_OFF"):
        raise_error(ERR_WORKPAPER_INVALID_STATE,
                    "workpaper must be SUBMITTED or SIGNED_OFF to return")
    _check_unlocked(wp)
    eng = _require_fieldwork_engagement(wp)
    # Stage 8: segregation of duties
    if caller.user_id == wp["preparer_auditor_id"]:
        raise_error(ERR_WORKPAPER_SELF_REVIEW, "preparer cannot return own workpaper")
    was_signed_off = wp["status"] == "SIGNED_OFF"
    wp["status"] = "RETURNED"
    wp["reviewer_auditor_id"] = caller.user_id
    wp["review_note"] = note
    if was_signed_off:
        wp["signed_off_at"] = None  # compensating action
    touch(wp)
    recompute_engagement_hours(eng)
    touch(eng)
    return success_object(public(wp))


@bp.post("/audit/workpapers/<rid>/revise")
def revise_workpaper(rid):
    caller = authorized(["FieldAuditor"])
    wp = require_path("workpapers", rid)
    # Stage 7: from-state, lock, engagement gate
    if wp["status"] != "RETURNED":
        raise_error(ERR_WORKPAPER_INVALID_STATE, "workpaper is not RETURNED")
    _check_unlocked(wp)
    _require_fieldwork_engagement(wp)
    # Stage 8: ownership — only the preparer may reopen for revision
    if caller.user_id != wp["preparer_auditor_id"]:
        raise_error(ERR_NOT_WORKPAPER_PREPARER, "only the preparer may revise")
    wp["status"] = "DRAFT"
    wp["review_note"] = None  # revision loop clears the note
    touch(wp)
    return success_object(public(wp))
