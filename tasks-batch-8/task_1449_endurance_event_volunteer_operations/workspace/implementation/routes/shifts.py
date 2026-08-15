"""Shift endpoints."""
from flask import Blueprint, request

import errors
from db import store
from middleware import require_roles
from response import success_object, success_list
from util import get_body, require_field, as_string, as_int, normalize_iso, parse_dt
from services.core import (
    make_record, touch, paginate, sort_by_created, serialize_shift,
    get_event_or_404, get_role_or_404, get_segment_or_404, get_shift_or_404,
)
from services.cascade import cancel_signup_record

bp = Blueprint("shifts", __name__)
ANY = ("Anonymous", "Volunteer", "Captain", "GroupLeader", "VolunteerCoordinator", "EventDirector")


@bp.post("/volunteer-ops/shifts")
def create_shift():
    require_roles("VolunteerCoordinator")
    body = get_body()
    event_id = as_string(require_field(body, "event_id"), "event_id")
    ev = get_event_or_404(event_id)
    role_entry_id = as_string(require_field(body, "role_entry_id"), "role_entry_id")
    role = get_role_or_404(role_entry_id)
    segment_id = as_string(require_field(body, "segment_id"), "segment_id")
    seg = get_segment_or_404(segment_id)
    start_at = normalize_iso(as_string(require_field(body, "start_at"), "start_at"))
    end_at = normalize_iso(as_string(require_field(body, "end_at"), "end_at"))
    headcount = as_int(require_field(body, "required_headcount"), "required_headcount")

    # cross-event consistency
    if role["event_id"] != event_id or seg["event_id"] != event_id:
        raise errors.invalid_request("role_entry_id and segment_id must belong to the same event.")
    # role must be ACTIVE
    if role["status"] != "ACTIVE":
        raise errors.role_entry_not_active()
    if headcount < 1:
        raise errors.invalid_request("required_headcount must be >= 1.")
    start = parse_dt(start_at)
    end = parse_dt(end_at)
    ev_start = parse_dt(ev["event_start_at"])
    ev_end = parse_dt(ev["event_end_at"])
    if not (end > start):
        raise errors.invalid_request("end_at must be strictly after start_at.")
    if start < ev_start or end > ev_end:
        raise errors.invalid_request("Shift window must sit within the event bounds.")

    rec = make_record({
        "event_id": event_id,
        "role_entry_id": role_entry_id,
        "segment_id": segment_id,
        "start_at": start_at,
        "end_at": end_at,
        "required_headcount": headcount,
        "confirmed_count": 0,
        "checked_in_count": 0,
        "understaffed_alert": False,
        "status": "OPEN",
    })
    store.shifts[rec["id"]] = rec
    return success_object(serialize_shift(rec), status=201)


@bp.get("/volunteer-ops/shifts")
def list_shifts():
    require_roles(*ANY)
    event_id = request.args.get("event_id")
    role_entry_id = request.args.get("role_entry_id")
    segment_id = request.args.get("segment_id")
    items = [
        s for s in store.shifts.values()
        if (event_id is None or s["event_id"] == event_id)
        and (role_entry_id is None or s["role_entry_id"] == role_entry_id)
        and (segment_id is None or s["segment_id"] == segment_id)
    ]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_shift(s) for s in page], limit, offset, total)


@bp.get("/volunteer-ops/shifts/<shiftId>")
def get_shift(shiftId):
    require_roles(*ANY)
    shift = get_shift_or_404(shiftId)
    return success_object(serialize_shift(shift))


@bp.post("/volunteer-ops/shifts/<shiftId>/cancel")
def cancel_shift(shiftId):
    require_roles("VolunteerCoordinator")
    shift = get_shift_or_404(shiftId)
    if shift["status"] not in {"OPEN", "FULL"}:
        raise errors.shift_not_open()
    ev = store.events.get(shift["event_id"])
    if ev is None or ev["status"] not in {"DRAFT", "PUBLISHED"}:
        raise errors.invalid_event_state(
            "Manual shift cancel requires event status DRAFT or PUBLISHED.")
    shift["status"] = "CANCELLED"
    touch(shift)
    for su in list(store.signups.values()):
        if su["shift_id"] == shift["id"] and su["status"] in {
            "REQUESTED", "WAITLISTED", "APPROVED", "CONFIRMED"
        }:
            cancel_signup_record(su, fire_seat_open=False)
    return success_object(serialize_shift(shift))


@bp.post("/volunteer-ops/shifts/<shiftId>/reconcile")
def reconcile_shift(shiftId):
    require_roles("VolunteerCoordinator")
    shift = get_shift_or_404(shiftId)
    ev = store.events.get(shift["event_id"])
    if shift["status"] != "IN_PROGRESS":
        raise errors.invalid_event_state("Reconcile requires shift status IN_PROGRESS.")
    if ev is None or ev["status"] not in {"COMPLETED", "DEBRIEF_OPEN"}:
        raise errors.invalid_event_state(
            "Reconcile requires event status COMPLETED or DEBRIEF_OPEN.")
    unresolved = any(
        su["shift_id"] == shift["id"] and su["status"] in {"CONFIRMED", "CHECKED_IN"}
        for su in store.signups.values()
    )
    if unresolved:
        raise errors.shift_has_unresolved_signups()
    shift["status"] = "RECONCILED"
    touch(shift)
    return success_object(serialize_shift(shift))
