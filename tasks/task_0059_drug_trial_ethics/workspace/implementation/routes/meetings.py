from __future__ import annotations

"""Meeting + agenda item endpoints (and publish/open/close/cancel)."""

from flask import Blueprint, g, request

import db
from clock import iso, now, parse_iso
from errors import (
    ERR_AGENDA_LEAD_TIME_VIOLATION,
    ERR_FIELD_VALIDATION,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_MEMBER_NOT_QUALIFIED,
    ERR_MEMBER_RECUSED,
    ERR_NOT_FOUND,
    ERR_REFERENCE_NOT_FOUND,
    raise_error,
)
from middleware import require_role
from response import success_array, success_empty, success_object
from serializers import serialize_agenda_item, serialize_meeting
import services_state as svc
from validation import (
    check_version,
    get_json_body,
    get_pagination,
    optional_enum,
    require_datetime,
    require_enum,
    require_string,
    sort_default,
)

bp = Blueprint("meetings", __name__)

REVIEW_KINDS = {"INITIAL_REVIEW", "SECONDARY_REVIEW", "ANNUAL_REVIEW",
                "AMENDMENT_REVIEW", "FINAL_REPORT_REVIEW"}


# ---------------------------------------------------------------------------
# POST /ethics/meetings
# ---------------------------------------------------------------------------
@bp.post("/ethics/meetings")
def create_meeting():
    require_role({"Secretary"})
    body = get_json_body()
    meeting_type = require_enum(body, "meeting_type", {"STANDARD", "EXPEDITED"})
    scheduled_at = require_datetime(body, "scheduled_at")
    convener_member_id = require_string(body, "convener_member_id")
    convener = db.committee_members.get(convener_member_id)
    if not convener:
        raise_error(ERR_REFERENCE_NOT_FOUND, f"convener_member_id {convener_member_id} not found")

    # Qualification + active check (priority 9)
    if convener["qualification"] != "MEDICAL_EXPERT" or not svc.compute_member_is_active(convener):
        raise_error(ERR_MEMBER_NOT_QUALIFIED,
                    "Convener must be an active MEDICAL_EXPERT")

    with db.lock:
        lead = 168 if meeting_type == "STANDARD" else 24
        m = svc.new_versioned({
            "meeting_type": meeting_type,
            "scheduled_at": scheduled_at,
            "status": "SCHEDULED",
            "agenda_published_at": None,
            "convener_member_id": convener_member_id,
            "lead_time_hours": lead,
        })
        db.meetings[m["id"]] = m
    return success_object(serialize_meeting(m), 201)


# ---------------------------------------------------------------------------
# GET /ethics/meetings/{id}
# ---------------------------------------------------------------------------
@bp.get("/ethics/meetings/<mid>")
def get_meeting(mid):
    require_role({"Secretary", "Chairperson", "CommitteeMember"})
    m = db.meetings.get(mid)
    if not m:
        raise_error(ERR_NOT_FOUND, f"Meeting {mid} not found")
    return success_object(serialize_meeting(m))


# ---------------------------------------------------------------------------
# GET /ethics/meetings
# ---------------------------------------------------------------------------
@bp.get("/ethics/meetings")
def list_meetings():
    require_role({"Secretary", "Chairperson", "CommitteeMember"})
    limit, offset = get_pagination()
    status_f = request.args.get("status")
    type_f = request.args.get("meeting_type")
    rows = list(db.meetings.values())
    if status_f:
        rows = [r for r in rows if r["status"] == status_f]
    if type_f:
        rows = [r for r in rows if r["meeting_type"] == type_f]
    rows = sort_default(rows)
    total = len(rows)
    page = svc.paginate(rows, limit, offset)
    return success_array([serialize_meeting(r) for r in page],
                         limit=limit, offset=offset, total_count=total)


# ---------------------------------------------------------------------------
# POST /ethics/meetings/{id}/agenda-items
# ---------------------------------------------------------------------------
@bp.post("/ethics/meetings/<mid>/agenda-items")
def add_agenda_item(mid):
    require_role({"Secretary"})
    m = db.meetings.get(mid)
    if not m:
        raise_error(ERR_NOT_FOUND, f"Meeting {mid} not found")
    body = get_json_body()
    application_id = require_string(body, "application_id")
    review_kind = require_enum(body, "review_kind", REVIEW_KINDS)
    annual_report_id = body.get("annual_report_id")
    rectification_id = body.get("rectification_id")

    app = db.applications.get(application_id)
    if not app:
        raise_error(ERR_REFERENCE_NOT_FOUND, f"application_id {application_id} not found")
    if annual_report_id:
        if not db.annual_reports.get(annual_report_id):
            raise_error(ERR_REFERENCE_NOT_FOUND, f"annual_report_id {annual_report_id} not found")
    if rectification_id:
        if not db.rectifications.get(rectification_id):
            raise_error(ERR_REFERENCE_NOT_FOUND, f"rectification_id {rectification_id} not found")

    with db.lock:
        if m["status"] not in ("SCHEDULED",):
            # Allowed to add to SCHEDULED meeting only
            raise_error(ERR_INVALID_STATE,
                        f"Cannot add agenda items to a '{m['status']}' meeting")
        # Convener conflict gate when adding application
        convener_id = m["convener_member_id"]
        if svc.member_has_active_conflict(convener_id, application_id):
            raise_error(ERR_MEMBER_RECUSED,
                        "Convener has an active conflict against this application")

        item = svc.new_versioned({
            "meeting_id": mid,
            "application_id": application_id,
            "pinned_submission_version": None,
            "review_kind": review_kind,
            "status": "DRAFT",
            "quorum_required": None,
            "eligible_voter_count": None,
            "annual_report_id": annual_report_id,
            "rectification_id": rectification_id,
        })
        db.agenda_items[item["id"]] = item

        # Note: Application moves to IN_REVIEW when meeting is opened, not here.
    return success_object(serialize_agenda_item(item), 201)


# ---------------------------------------------------------------------------
# POST /ethics/meetings/{id}/publish-agenda
# ---------------------------------------------------------------------------
@bp.post("/ethics/meetings/<mid>/publish-agenda")
def publish_agenda(mid):
    require_role({"Secretary"})
    m = db.meetings.get(mid)
    if not m:
        raise_error(ERR_NOT_FOUND, f"Meeting {mid} not found")
    body = get_json_body()

    with db.lock:
        if m["status"] != "SCHEDULED":
            raise_error(ERR_INVALID_STATE,
                        f"Cannot publish agenda for a '{m['status']}' meeting")
        items = [it for it in db.agenda_items.values() if it["meeting_id"] == mid]
        if not items:
            raise_error(ERR_INVALID_STATE, "Meeting has no agenda items to publish")

        # Lead-time check (priority 10)
        scheduled = parse_iso(m["scheduled_at"])
        secs_until = (scheduled - now()).total_seconds()
        required = m["lead_time_hours"] * 3600
        if secs_until < required:
            raise_error(ERR_AGENDA_LEAD_TIME_VIOLATION,
                        "Insufficient lead time between now and scheduled meeting")

        check_version(body, m)

        # Freeze each agenda item
        for it in items:
            app = db.applications.get(it["application_id"])
            if not app:
                continue
            it["pinned_submission_version"] = app.get("current_submission_version", 0)
            elig = svc.compute_eligible_voter_count(it["application_id"])
            it["eligible_voter_count"] = elig
            it["quorum_required"] = svc.compute_quorum_required(elig)
            it["status"] = "PUBLISHED"
            svc.bump(it)

            # Rectification linked: advance to UNDER_SECONDARY_REVIEW
            if it["review_kind"] == "SECONDARY_REVIEW" and it.get("rectification_id"):
                rec = db.rectifications.get(it["rectification_id"])
                if rec and rec["status"] == "RESPONDED":
                    rec["status"] = "UNDER_SECONDARY_REVIEW"
                    svc.bump(rec)

            # AnnualReport linked: advance to SCHEDULED_FOR_REVIEW
            if it.get("annual_report_id"):
                ar = db.annual_reports.get(it["annual_report_id"])
                if ar and ar["status"] == "SUBMITTED":
                    ar["status"] = "SCHEDULED_FOR_REVIEW"
                    svc.bump(ar)

        m["agenda_published_at"] = iso()
        m["status"] = "AGENDA_PUBLISHED"
        svc.bump(m)
    return success_object(serialize_meeting(m))


# ---------------------------------------------------------------------------
# POST /ethics/meetings/{id}/open
# ---------------------------------------------------------------------------
@bp.post("/ethics/meetings/<mid>/open")
def open_meeting(mid):
    require_role({"Secretary"})
    m = db.meetings.get(mid)
    if not m:
        raise_error(ERR_NOT_FOUND, f"Meeting {mid} not found")
    body = get_json_body()

    with db.lock:
        if m["status"] != "AGENDA_PUBLISHED":
            raise_error(ERR_INVALID_STATE,
                        f"Cannot open meeting from state '{m['status']}'")
        # scheduled_at reached
        sched = parse_iso(m["scheduled_at"])
        if now() < sched:
            raise_error(ERR_INVALID_STATE,
                        "Meeting scheduled time has not been reached")

        check_version(body, m)

        for it in db.agenda_items.values():
            if it["meeting_id"] == mid and it["status"] == "PUBLISHED":
                it["status"] = "OPEN_FOR_VOTING"
                svc.bump(it)
                # Application moves into IN_REVIEW for INITIAL/SECONDARY reviews
                app = db.applications.get(it["application_id"])
                if app and it["review_kind"] in ("INITIAL_REVIEW", "SECONDARY_REVIEW"):
                    if app["status"] == "PENDING_REVIEW":
                        svc.application_set_status(app, "IN_REVIEW")
                    elif app["status"] == "DEFERRED" and it["review_kind"] == "SECONDARY_REVIEW":
                        svc.application_set_status(app, "IN_REVIEW")
                    elif app["status"] == "APPROVED_WITH_MOD" and it["review_kind"] == "SECONDARY_REVIEW":
                        # stays in APPROVED_WITH_MOD throughout rectification process
                        pass
        m["status"] = "IN_SESSION"
        svc.bump(m)
    return success_object(serialize_meeting(m))


# ---------------------------------------------------------------------------
# POST /ethics/meetings/{id}/close
# ---------------------------------------------------------------------------
@bp.post("/ethics/meetings/<mid>/close")
def close_meeting(mid):
    require_role({"Secretary"})
    m = db.meetings.get(mid)
    if not m:
        raise_error(ERR_NOT_FOUND, f"Meeting {mid} not found")
    body = get_json_body()

    with db.lock:
        if m["status"] != "IN_SESSION":
            raise_error(ERR_INVALID_STATE,
                        f"Cannot close meeting in '{m['status']}'")
        items = [it for it in db.agenda_items.values() if it["meeting_id"] == mid]
        if any(it["status"] not in ("RESOLVED", "CLOSED_WITHOUT_QUORUM") for it in items):
            raise_error(ERR_INVALID_STATE,
                        "All agenda items must be RESOLVED or CLOSED_WITHOUT_QUORUM before close")
        check_version(body, m)
        m["status"] = "CLOSED"
        svc.bump(m)
    return success_object(serialize_meeting(m))


# ---------------------------------------------------------------------------
# DELETE /ethics/meetings/{id}
# ---------------------------------------------------------------------------
@bp.delete("/ethics/meetings/<mid>")
def cancel_meeting(mid):
    require_role({"Secretary"})
    m = db.meetings.get(mid)
    if not m:
        raise_error(ERR_NOT_FOUND, f"Meeting {mid} not found")
    with db.lock:
        if m["status"] != "SCHEDULED":
            raise_error(ERR_INVALID_STATE,
                        f"Cannot cancel meeting in '{m['status']}'")
        # cascade-delete agenda items
        to_delete = [iid for iid, it in db.agenda_items.items() if it["meeting_id"] == mid]
        for iid in to_delete:
            del db.agenda_items[iid]
        m["status"] = "CANCELLED"
        svc.bump(m)
    return success_empty(204)


# ---------------------------------------------------------------------------
# GET /ethics/agenda-items/{id}
# ---------------------------------------------------------------------------
@bp.get("/ethics/agenda-items/<iid>")
def get_agenda_item(iid):
    require_role({"Secretary", "Chairperson", "CommitteeMember", "Applicant"})
    it = db.agenda_items.get(iid)
    if not it:
        raise_error(ERR_NOT_FOUND, f"AgendaItem {iid} not found")
    if g.user_role == "Applicant":
        app = db.applications.get(it["application_id"])
        if not app or app["applicant_id"] != g.user_id:
            raise_error(ERR_FORBIDDEN, "Applicant may only read agenda items for their own application")
    return success_object(serialize_agenda_item(it))
