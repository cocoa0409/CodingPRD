"""Court-event routes (PRD §3.8)."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

import db
from db import (
    court_events, cases, stamp_common, bump,
    parse_iso_dt, current_clock_dt,
)
from errors import (
    APIError,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_EVENT_IN_PAST,
    ERR_COURT_EVENT_CONFLICT,
)
from middleware import require_auth, get_json_body
from response import ok_object, ok_array, paginate_params, slice_page
from services.validation import (
    require_str, require_int, require_enum, require_iso8601,
    get_or_404_path, get_or_fk_404,
)


bp = Blueprint("court_events", __name__)


VALID_EVENT_TYPES = {"FILING", "HEARING", "TRIAL", "MEDIATION"}
CONFLICT_TYPES = {"HEARING", "TRIAL", "MEDIATION"}


def _view(e: dict) -> dict:
    return {
        "id": e["id"],
        "case_id": e["case_id"],
        "event_type": e["event_type"],
        "scheduled_at": e["scheduled_at"],
        "duration_minutes": e["duration_minutes"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


@bp.post("/court-events")
def create_event():
    require_auth({"Attorney", "ManagingPartner"})()
    body = get_json_body()
    case_id = require_str(body, "case_id")
    event_type = require_enum(body, "event_type", VALID_EVENT_TYPES)
    scheduled_at = require_iso8601(body, "scheduled_at")
    duration = body.get("duration_minutes", 60)
    if isinstance(duration, bool) or not isinstance(duration, int):
        raise APIError(ERR_INVALID_REQUEST, 400, "duration_minutes must be an integer")
    if duration <= 0 or duration > 600:
        raise APIError(ERR_INVALID_REQUEST, 400, "duration_minutes must be in (0, 600]")

    case = get_or_fk_404(cases, case_id, "Case")

    sched_dt = parse_iso_dt(scheduled_at)
    now = current_clock_dt()
    # PRD §3.8: scheduled_at must be strictly later than now.
    if sched_dt <= now:
        raise APIError(
            ERR_EVENT_IN_PAST, 422,
            "scheduled_at must be strictly later than current clock",
        )

    # Conflict avoidance for HEARING/TRIAL/MEDIATION on same case.
    if event_type in CONFLICT_TYPES:
        new_start = sched_dt - timedelta(hours=24)
        new_end = sched_dt + timedelta(minutes=duration) + timedelta(hours=24)
        for ev in court_events.values():
            if ev["case_id"] != case_id:
                continue
            if ev["status"] != "SCHEDULED":
                continue
            ex_start = parse_iso_dt(ev["scheduled_at"])
            ex_end = ex_start + timedelta(minutes=int(ev["duration_minutes"]))
            # Closed interval intersection: overlap iff new_start <= ex_end
            # AND ex_start <= new_end.
            if new_start <= ex_end and ex_start <= new_end:
                raise APIError(
                    ERR_COURT_EVENT_CONFLICT, 409,
                    "CourtEvent conflicts with an existing SCHEDULED event on this case",
                )

    e = {
        "case_id": case_id,
        "event_type": event_type,
        "scheduled_at": scheduled_at,
        "duration_minutes": duration,
        "status": "SCHEDULED",
    }
    stamp_common(e)
    court_events[e["id"]] = e
    return ok_object(_view(e), 201)


@bp.get("/court-events/<eid>")
def get_event(eid):
    require_auth({"Paralegal", "Attorney", "ManagingPartner"})()
    e = get_or_404_path(court_events, eid, "CourtEvent")
    return ok_object(_view(e), 200)


@bp.get("/court-events")
def list_events():
    require_auth({"Paralegal", "Attorney", "ManagingPartner"})()
    limit, offset = paginate_params(request.args)
    case_id = request.args.get("case_id")
    status = request.args.get("status")
    event_type = request.args.get("event_type")
    items = list(court_events.values())
    if case_id is not None:
        items = [e for e in items if e["case_id"] == case_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    if event_type is not None:
        items = [e for e in items if e["event_type"] == event_type]
    items.sort(key=lambda e: e["created_at"])
    page, total = slice_page(items, limit, offset)
    return ok_array([_view(e) for e in page], limit, offset, total, 200)


@bp.post("/court-events/<eid>/mark-occurred")
def mark_occurred(eid):
    require_auth({"Attorney"})()
    e = get_or_404_path(court_events, eid, "CourtEvent")
    if e["status"] != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409, "CourtEvent must be SCHEDULED to mark occurred")
    now = current_clock_dt()
    sched = parse_iso_dt(e["scheduled_at"])
    if now < sched:
        raise APIError(
            ERR_INVALID_STATE, 409,
            "Current clock has not reached scheduled_at",
        )
    e["status"] = "OCCURRED"
    bump(e)
    return ok_object(_view(e), 200)


@bp.post("/court-events/<eid>/cancel")
def cancel_event(eid):
    require_auth({"Attorney", "ManagingPartner"})()
    e = get_or_404_path(court_events, eid, "CourtEvent")
    if e["status"] != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409, "CourtEvent must be SCHEDULED to cancel")
    e["status"] = "CANCELLED"
    bump(e)
    return ok_object(_view(e), 200)
