"""Event endpoints."""

from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, request

import db
from common import (
    require_role, get_json_body, stamp_common_create, bump,
    success, must_exist, get_pagination, paginate_list, parse_iso8601,
    clock_now_dt, clock_now_iso,
)
from errors import (
    raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND,
    ERR_CAPACITY_EXCEEDED, ERR_EVENT_NOT_ENDED, ERR_SECURITY_HOLD_TRIGGERED,
)
from routes.facility import _upcoming_booked_hours

bp = Blueprint("events", __name__)


EVENT_TYPES = {"SERVICE", "CLASS", "MEETING", "OUTREACH"}
PRIORITY_WEIGHT = {"SERVICE": 1.00, "CLASS": 0.80, "MEETING": 0.60, "OUTREACH": 0.90}


def _round_half_up_2(v):
    return Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _volunteer_filled_count(event_id):
    return sum(
        1 for va in db.volunteer_assignments.values()
        if va.get("event_id") == event_id
        and va.get("status") in ("ACCEPTED", "CHECKED_IN", "COMPLETED")
    )


def _attendance_count(event_id):
    return sum(
        1 for c in db.child_checkins.values()
        if c.get("event_id") == event_id
        and c.get("status") in ("CHECKED_IN", "CHECKED_OUT")
    )


def _coverage_score(event):
    filled = _volunteer_filled_count(event["id"])
    slots = event["volunteer_slots"]
    if slots > 0:
        fill_ratio = min(1.0, filled / slots)
    else:
        fill_ratio = 1.0
    starts = parse_iso8601(event["starts_at"])
    now = clock_now_dt()
    hours_to_event = max(0.0, (starts - now).total_seconds() / 3600.0)
    urgency = max(0.0, 1.0 - hours_to_event / 72.0)
    pw = PRIORITY_WEIGHT[event["event_type"]]
    raw = 100.0 * pw * (0.60 * fill_ratio + 0.40 * (1 - urgency))
    return float(_round_half_up_2(raw))


@bp.route("/events", methods=["POST"])
def create_event():
    require_role({"Coordinator", "PlatformAdmin"})
    body = get_json_body()
    for k in ("name", "event_type", "starts_at", "ends_at", "expected_attendance", "volunteer_slots"):
        if k not in body or body[k] is None:
            raise_err(ERR_INVALID_REQUEST, f"{k} is required")
    if not isinstance(body["name"], str) or body["name"] == "":
        raise_err(ERR_INVALID_REQUEST, "name must be a non-empty string")
    if body["event_type"] not in EVENT_TYPES:
        raise_err(ERR_INVALID_REQUEST, "invalid event_type")
    try:
        starts = parse_iso8601(body["starts_at"])
        ends = parse_iso8601(body["ends_at"])
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "starts_at/ends_at must be ISO8601")
    if ends <= starts:
        raise_err(ERR_INVALID_REQUEST, "ends_at must be > starts_at")
    for k in ("expected_attendance", "volunteer_slots"):
        if not isinstance(body[k], int) or isinstance(body[k], bool):
            raise_err(ERR_INVALID_REQUEST, f"{k} must be an integer")
        if body[k] < 0:
            raise_err(ERR_INVALID_REQUEST, f"{k} must be >= 0")

    facility_id = body.get("facility_id")
    facility = None
    if facility_id is not None:
        facility = db.facilities.get(facility_id)
        if facility is None:
            raise_err(ERR_NOT_FOUND, "facility_id not found")

    if facility is not None:
        if body["expected_attendance"] > facility["capacity"]:
            raise_err(ERR_CAPACITY_EXCEEDED, "expected_attendance exceeds facility capacity")

    rec = {
        "name": body["name"],
        "event_type": body["event_type"],
        "facility_id": facility_id,
        "starts_at": body["starts_at"],
        "ends_at": body["ends_at"],
        "expected_attendance": body["expected_attendance"],
        "volunteer_slots": body["volunteer_slots"],
        "status": "SCHEDULED",
        "volunteer_filled_count": 0,
        "attendance_count": 0,
        "coverage_score": 0.0,
    }
    stamp_common_create(rec)
    db.events[rec["id"]] = rec
    return success(rec, 201)


@bp.route("/events/<eid>/cancel", methods=["POST"])
def cancel_event(eid):
    require_role({"Coordinator", "PlatformAdmin"})
    rec = must_exist(db.events, eid, "Event")
    if rec["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "event must be SCHEDULED to cancel")

    rec["status"] = "CANCELLED"
    bump(rec)

    # Link 1: cascade CONFIRMED FacilityBookings to CANCELLED.
    affected_facilities = set()
    for b in list(db.facility_bookings.values()):
        if b.get("event_id") == eid and b.get("status") == "CONFIRMED":
            b["status"] = "CANCELLED"
            bump(b)
            affected_facilities.add(b["facility_id"])
    # Link 2: recompute upcoming_booked_hours on each affected facility.
    for fid in affected_facilities:
        f = db.facilities.get(fid)
        if f is not None:
            f["upcoming_booked_hours"] = _upcoming_booked_hours(fid)
            bump(f)

    # Parallel: INVITED/ACCEPTED VolunteerAssignments -> CANCELLED.
    for va in list(db.volunteer_assignments.values()):
        if va.get("event_id") == eid and va.get("status") in ("INVITED", "ACCEPTED"):
            va["status"] = "CANCELLED"
            bump(va)

    # Parallel: CHECKED_IN ChildCheckIns -> SECURITY_HOLD (STAFF_HOLD).
    for cc in list(db.child_checkins.values()):
        if cc.get("event_id") == eid and cc.get("status") == "CHECKED_IN":
            cc["status"] = "SECURITY_HOLD"
            cc["hold_reason"] = "STAFF_HOLD"
            bump(cc)

    # Refresh volunteer_filled_count on event (some ACCEPTED were cancelled).
    rec["volunteer_filled_count"] = _volunteer_filled_count(eid)
    return success(rec, 200)


@bp.route("/events/<eid>/complete", methods=["POST"])
def complete_event(eid):
    require_role({"Coordinator", "PlatformAdmin"})
    rec = must_exist(db.events, eid, "Event")
    if rec["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "event must be SCHEDULED to complete")
    ends = parse_iso8601(rec["ends_at"])
    now = clock_now_dt()
    if now < ends:
        raise_err(ERR_EVENT_NOT_ENDED, "event has not ended yet")
    # Rung 7: children still checked in / on hold.
    for cc in db.child_checkins.values():
        if cc.get("event_id") == eid and cc.get("status") in ("CHECKED_IN", "SECURITY_HOLD"):
            raise_err(ERR_SECURITY_HOLD_TRIGGERED, "children still checked in — cannot complete")

    rec["status"] = "COMPLETED"
    bump(rec)
    # CHECKED_IN VolunteerAssignments -> COMPLETED.
    for va in db.volunteer_assignments.values():
        if va.get("event_id") == eid and va.get("status") == "CHECKED_IN":
            va["status"] = "COMPLETED"
            bump(va)
    return success(rec, 200)


@bp.route("/events/<eid>", methods=["GET"])
def get_event(eid):
    require_role({"Coordinator", "FinanceAdmin", "Member", "PlatformAdmin"})
    rec = must_exist(db.events, eid, "Event")
    out = dict(rec)
    # Recompute derived fields on read.
    out["volunteer_filled_count"] = _volunteer_filled_count(eid)
    out["attendance_count"] = _attendance_count(eid)
    # Reflect refreshed volunteer_filled_count in coverage_score computation.
    tmp = dict(rec)
    tmp["volunteer_filled_count"] = out["volunteer_filled_count"]
    out["coverage_score"] = _coverage_score(tmp)
    return success(out, 200)


@bp.route("/events", methods=["GET"])
def list_events():
    require_role({"Coordinator", "FinanceAdmin", "Member", "PlatformAdmin"})
    limit, offset = get_pagination()
    items = list(db.events.values())
    for k in ("facility_id", "event_type", "status"):
        v = request.args.get(k)
        if v:
            items = [e for e in items if e.get(k) == v]
    # Recompute derived fields on each item.
    out = []
    for e in items:
        eo = dict(e)
        eo["volunteer_filled_count"] = _volunteer_filled_count(e["id"])
        eo["attendance_count"] = _attendance_count(e["id"])
        tmp = dict(e)
        tmp["volunteer_filled_count"] = eo["volunteer_filled_count"]
        eo["coverage_score"] = _coverage_score(tmp)
        out.append(eo)
    page, meta = paginate_list(out, limit, offset)
    return success(page, 200, meta_extra=meta)
