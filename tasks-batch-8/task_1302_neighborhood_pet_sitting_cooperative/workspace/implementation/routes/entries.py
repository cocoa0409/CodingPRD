"""EntryLog endpoints: append and list (immutable audit trail)."""

from datetime import timedelta

from flask import Blueprint, request

import clock
import db
from errors import (
    ApiError,
    ERR_ACCESS_NOT_HANDED_OFF,
    ERR_ENTRY_OUT_OF_WINDOW,
    ERR_INVALID_REQUEST,
)
from middleware import body, paginate, require_roles
from response import created
from routes.assignments import get_assignment_or_404
from serializers import entry_view
from services.calc import handoff_for_assignment
from util import new_id, parse_dt, touch

bp = Blueprint("entries", __name__)

EVENT_TYPES = {
    "CHECK_IN",
    "CHECK_OUT",
    "INCIDENT_NOTE",
    "PET_FED",
    "MEDICATION_GIVEN",
    "VET_VISIT",
}
NOTES_REQUIRED = {"INCIDENT_NOTE", "MEDICATION_GIVEN"}


@bp.post("/coop/sitting-assignments/<assignment_id>/entry-logs")
def create_entry(assignment_id):
    user_id, _ = require_roles("Member")
    assignment = get_assignment_or_404(assignment_id)
    data = body()
    event_type = data.get("event_type")
    if event_type not in EVENT_TYPES:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "event_type must be one of CHECK_IN, CHECK_OUT, INCIDENT_NOTE, PET_FED, MEDICATION_GIVEN, VET_VISIT",
        )
    try:
        occurred_at = parse_dt(data.get("occurred_at"))
    except (TypeError, ValueError):
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "occurred_at must be a valid ISO 8601 datetime"
        )
    # Priority 12: a first CHECK_IN may not begin work before the handoff is
    # HANDED_OFF.
    first_checkin = event_type == "CHECK_IN" and assignment["status"] == "CONFIRMED"
    if first_checkin:
        handoff = handoff_for_assignment(assignment["id"])
        if handoff is None or handoff["status"] != "HANDED_OFF":
            raise ApiError(
                ERR_ACCESS_NOT_HANDED_OFF,
                409,
                "CHECK_IN requires the access handoff to be HANDED_OFF",
            )
    # Priority 13: entries only within [scheduled_start - 30m,
    # scheduled_end + 4h], inclusive at both ends.
    window_lo = assignment["scheduled_start_at"] - timedelta(minutes=30)
    window_hi = assignment["scheduled_end_at"] + timedelta(hours=4)
    if occurred_at < window_lo or occurred_at > window_hi:
        raise ApiError(
            ERR_ENTRY_OUT_OF_WINDOW,
            422,
            "occurred_at is outside the assignment's entry window",
        )
    notes = data.get("notes")
    if event_type in NOTES_REQUIRED and (
        not isinstance(notes, str) or not notes.strip()
    ):
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            f"notes is required for {event_type} entries",
        )
    if notes is not None and not isinstance(notes, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "notes must be a string")
    entry = {
        "id": new_id(),
        "created_at": clock.now(),
        "_seq": db.next_seq(),
        "sitting_assignment_id": assignment["id"],
        "actor_member_id": user_id,
        "event_type": event_type,
        "occurred_at": occurred_at,
        "notes": notes,
    }
    db.store["entries"][entry["id"]] = entry
    # First CHECK_IN moves the assignment and request to IN_PROGRESS and
    # stamps actual_start_at with the entry's occurred_at.
    if first_checkin:
        assignment["status"] = "IN_PROGRESS"
        assignment["actual_start_at"] = occurred_at
        touch(assignment)
        req = db.store["requests"].get(assignment["sitting_request_id"])
        if req is not None:
            req["status"] = "IN_PROGRESS"
            touch(req)
    return created(entry_view(entry))


@bp.get("/coop/sitting-assignments/<assignment_id>/entry-logs")
def list_entries(assignment_id):
    require_roles("CoopAdmin", "Member")
    assignment = get_assignment_or_404(assignment_id)
    items = [
        e
        for e in db.store["entries"].values()
        if e["sitting_assignment_id"] == assignment["id"]
    ]
    event_type = request.args.get("event_type")
    if event_type is not None:
        items = [e for e in items if e["event_type"] == event_type]
    return paginate(items, entry_view)
