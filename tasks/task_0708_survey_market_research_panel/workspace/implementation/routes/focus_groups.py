"""Facility, FocusGroup, FocusGroupBooking endpoints (PRD §3.8, §2.10).

Temporal rules:
- Facility double-booking: a session's [starts_at, ends_at) extended by the
  facility turnaround buffer must not overlap any other SCHEDULED session on the
  same facility (ERR_FACILITY_DOUBLE_BOOKED, 409).
- Panelist schedule conflict: a panelist's CONFIRMED bookings must not overlap in
  [starts_at, ends_at) across two SCHEDULED sessions, no buffer
  (ERR_PANELIST_SCHEDULE_CONFLICT, 409).
"""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import errors
import lookup
import response
import validation
from middleware import get_identity, require_roles, require_owner
from services import core

bp = Blueprint("focus_groups", __name__)


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval overlap test: [a_start, a_end) ∩ [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


# ----- Facilities -----
@bp.post("/facilities")
def create_facility():
    user_id, role = get_identity()
    require_roles(role, {"FieldCoordinator"})
    body = validation.get_json_body()
    name = validation.require_str(body, "name")
    capacity = validation.require_int(body, "capacity", minimum=1)
    turnaround = validation.opt_int(body, "turnaround_minutes", default=0, minimum=0)

    rec = db.base_record(common_fields=True)
    rec.update({
        "name": name,
        "capacity": capacity,
        "turnaround_minutes": turnaround,
        "status": "AVAILABLE",
    })
    db.facilities[rec["id"]] = rec
    return response.object_response(core.serialize_facility(rec), status=201)


@bp.get("/facilities/<fid>")
def get_facility(fid):
    user_id, role = get_identity()
    require_roles(role, {"FieldCoordinator", "ResearchManager"})
    f = lookup.facility(fid)
    return response.object_response(core.serialize_facility(f))


# ----- Focus groups -----
@bp.post("/focus-groups")
def create_focus_group():
    user_id, role = get_identity()
    require_roles(role, {"FieldCoordinator"})
    body = validation.get_json_body()
    study_id = validation.require_str(body, "study_id")
    facility_id = validation.require_str(body, "facility_id")
    starts_at_raw = validation.require_str(body, "starts_at")
    ends_at_raw = validation.require_str(body, "ends_at")
    seats = validation.require_int(body, "seats", minimum=1)

    lookup.study(study_id)
    facility = lookup.facility(facility_id)

    try:
        starts_at = clock.parse_iso8601(starts_at_raw)
        ends_at = clock.parse_iso8601(ends_at_raw)
    except (ValueError, TypeError):
        errors.fail(errors.ERR_VALIDATION, "starts_at/ends_at must be ISO 8601")

    # seats must not exceed capacity (priority/422).
    if seats > facility["capacity"]:
        errors.fail(errors.ERR_SEATS_EXCEED_CAPACITY, "seats exceed facility capacity")

    # Facility double-booking with turnaround buffer (409).
    buffer = timedelta(minutes=facility["turnaround_minutes"])
    new_start = starts_at - buffer
    new_end = ends_at + buffer
    for fg in db.focus_groups.values():
        if fg["facility_id"] != facility_id or fg["status"] != "SCHEDULED":
            continue
        ex_start = clock.parse_iso8601(fg["starts_at"])
        ex_end = clock.parse_iso8601(fg["ends_at"])
        if _overlaps(new_start, new_end, ex_start, ex_end):
            errors.fail(errors.ERR_FACILITY_DOUBLE_BOOKED,
                        "Facility double-booked for this window")

    rec = db.base_record(common_fields=True)
    rec.update({
        "study_id": study_id,
        "facility_id": facility_id,
        "starts_at": starts_at_raw,
        "ends_at": ends_at_raw,
        "seats": seats,
        "status": "SCHEDULED",
    })
    db.focus_groups[rec["id"]] = rec
    return response.object_response(core.serialize_focus_group(rec), status=201)


@bp.get("/focus-groups")
def list_focus_groups():
    user_id, role = get_identity()
    require_roles(role, {"FieldCoordinator", "ResearchManager", "PanelOps"})
    study_id = request.args.get("study_id")
    facility_id = request.args.get("facility_id")
    status = request.args.get("status")
    records = []
    for fg in db.focus_groups.values():
        if study_id is not None and fg["study_id"] != study_id:
            continue
        if facility_id is not None and fg["facility_id"] != facility_id:
            continue
        if status is not None and fg["status"] != status:
            continue
        records.append(fg)
    window, limit, offset, total = validation.paginate(records)
    return response.array_response(
        [core.serialize_focus_group(fg) for fg in window], limit, offset, total)


@bp.get("/focus-groups/<gid>")
def get_focus_group(gid):
    user_id, role = get_identity()
    require_roles(role, {"FieldCoordinator", "ResearchManager", "PanelOps"})
    fg = lookup.focus_group(gid)
    return response.object_response(core.serialize_focus_group(fg))


@bp.post("/focus-groups/<gid>/cancel")
def cancel_focus_group(gid):
    user_id, role = get_identity()
    require_roles(role, {"FieldCoordinator"})
    fg = lookup.focus_group(gid)
    if fg["status"] != "SCHEDULED":
        errors.fail(errors.ERR_INVALID_STATE, "FocusGroup is not SCHEDULED")
    fg["status"] = "CANCELLED"
    db.touch(fg)
    # Cascade down: CONFIRMED bookings -> CANCELLED.
    for b in db.focus_group_bookings.values():
        if b["focus_group_id"] == fg["id"] and b["status"] == "CONFIRMED":
            b["status"] = "CANCELLED"
            db.touch(b)
    return response.object_response(core.serialize_focus_group(fg))


@bp.post("/focus-groups/<gid>/complete")
def complete_focus_group(gid):
    user_id, role = get_identity()
    require_roles(role, {"FieldCoordinator"})
    fg = lookup.focus_group(gid)
    if fg["status"] != "SCHEDULED":
        errors.fail(errors.ERR_INVALID_STATE, "FocusGroup is not SCHEDULED")
    # Precondition: starts_at <= clock now (PRD §3.8).
    if clock.parse_iso8601(fg["starts_at"]) > clock.now():
        errors.fail(errors.ERR_INVALID_STATE, "Session has not started yet")
    fg["status"] = "COMPLETED"
    db.touch(fg)
    return response.object_response(core.serialize_focus_group(fg))


# ----- Focus-group bookings -----
@bp.post("/focus-group-bookings")
def create_booking():
    user_id, role = get_identity()
    require_roles(role, {"Panelist", "FieldCoordinator"})
    body = validation.get_json_body()
    focus_group_id = validation.require_str(body, "focus_group_id")
    panelist_id = validation.require_str(body, "panelist_id")
    expected_version = validation.require_int(body, "expected_focus_group_version")

    fg = lookup.focus_group(focus_group_id)
    panelist = lookup.panelist(panelist_id)
    # Ownership (priority 4): entity-backed Panelist may only book themselves.
    require_owner(user_id, role, panelist["id"])

    # Booking is only valid on a SCHEDULED session (state).
    if fg["status"] != "SCHEDULED":
        errors.fail(errors.ERR_INVALID_STATE, "FocusGroup is not SCHEDULED")

    # Panelist schedule conflict (priority 9, 409): overlap with another CONFIRMED
    # booking on a SCHEDULED session (no buffer).
    new_start = clock.parse_iso8601(fg["starts_at"])
    new_end = clock.parse_iso8601(fg["ends_at"])
    for b in db.focus_group_bookings.values():
        if b["panelist_id"] != panelist_id or b["status"] != "CONFIRMED":
            continue
        other = db.focus_groups.get(b["focus_group_id"])
        if other is None or other["status"] != "SCHEDULED":
            continue
        o_start = clock.parse_iso8601(other["starts_at"])
        o_end = clock.parse_iso8601(other["ends_at"])
        if _overlaps(new_start, new_end, o_start, o_end):
            errors.fail(errors.ERR_PANELIST_SCHEDULE_CONFLICT,
                        "Panelist already booked on an overlapping session")

    # Session full (priority 10, 409): booked_n >= seats.
    if core.focus_group_booked_n(fg["id"]) >= fg["seats"]:
        errors.fail(errors.ERR_SESSION_FULL, "Session is full")

    # OCC (priority 16, 412): expected_focus_group_version must match.
    if expected_version != fg["version"]:
        errors.fail(errors.ERR_STALE_FOCUS_GROUP_VERSION, "Stale focus group version")

    rec = db.base_record(common_fields=True)
    rec.update({
        "focus_group_id": focus_group_id,
        "panelist_id": panelist_id,
        "expected_focus_group_version": expected_version,
        "status": "CONFIRMED",
    })
    db.focus_group_bookings[rec["id"]] = rec
    # booked_n is derived; bump the session version (PRD §3.8).
    db.touch(fg)
    return response.object_response(core.serialize_booking(rec), status=201)


@bp.get("/focus-group-bookings")
def list_bookings():
    user_id, role = get_identity()
    require_roles(role, {"FieldCoordinator", "ResearchManager", "PanelOps", "Panelist"})
    focus_group_id = request.args.get("focus_group_id")
    panelist_id = request.args.get("panelist_id")
    status = request.args.get("status")
    records = []
    for b in db.focus_group_bookings.values():
        if focus_group_id is not None and b["focus_group_id"] != focus_group_id:
            continue
        if panelist_id is not None and b["panelist_id"] != panelist_id:
            continue
        if status is not None and b["status"] != status:
            continue
        records.append(b)
    window, limit, offset, total = validation.paginate(records)
    return response.array_response(
        [core.serialize_booking(b) for b in window], limit, offset, total)


@bp.get("/focus-group-bookings/<bid>")
def get_booking(bid):
    user_id, role = get_identity()
    require_roles(role, {"FieldCoordinator", "ResearchManager", "PanelOps", "Panelist"})
    b = lookup.booking(bid)
    return response.object_response(core.serialize_booking(b))


@bp.post("/focus-group-bookings/<bid>/cancel")
def cancel_booking(bid):
    user_id, role = get_identity()
    require_roles(role, {"Panelist", "FieldCoordinator"})
    b = lookup.booking(bid)
    require_owner(user_id, role, b["panelist_id"])
    if b["status"] != "CONFIRMED":
        errors.fail(errors.ERR_INVALID_STATE, "Booking is not CONFIRMED")
    b["status"] = "CANCELLED"
    db.touch(b)
    # booked_n recomputed downward (derived); reflect the change on the session.
    fg = db.focus_groups.get(b["focus_group_id"])
    if fg is not None:
        db.touch(fg)
    return response.object_response(core.serialize_booking(b))


@bp.post("/focus-group-bookings/<bid>/mark_attended")
def mark_attended(bid):
    user_id, role = get_identity()
    require_roles(role, {"FieldCoordinator"})
    b = lookup.booking(bid)
    if b["status"] != "CONFIRMED":
        errors.fail(errors.ERR_INVALID_STATE, "Booking is not CONFIRMED")
    fg = lookup.focus_group(b["focus_group_id"])
    if fg["status"] != "COMPLETED":
        errors.fail(errors.ERR_INVALID_STATE, "Parent session is not COMPLETED")
    b["status"] = "ATTENDED"
    db.touch(b)
    return response.object_response(core.serialize_booking(b))


@bp.post("/focus-group-bookings/<bid>/mark_no_show")
def mark_no_show(bid):
    user_id, role = get_identity()
    require_roles(role, {"FieldCoordinator"})
    b = lookup.booking(bid)
    if b["status"] != "CONFIRMED":
        errors.fail(errors.ERR_INVALID_STATE, "Booking is not CONFIRMED")
    fg = lookup.focus_group(b["focus_group_id"])
    if fg["status"] != "COMPLETED":
        errors.fail(errors.ERR_INVALID_STATE, "Parent session is not COMPLETED")
    b["status"] = "NO_SHOW"
    db.touch(b)
    return response.object_response(core.serialize_booking(b))
