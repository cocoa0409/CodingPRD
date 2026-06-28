"""ProcedureBooking: Mohs/procedure scheduling on rooms (PRD 3.4)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import helpers
import response
from middleware import require

bp = Blueprint("procedure_bookings", __name__)

PROCEDURE_KINDS = {"EXCISION", "MOHS"}


@bp.post("/procedure-bookings")
@require("FrontDesk", "PracticeAdmin")
def create_booking():
    data = helpers.body()
    room_id = helpers.require_str(data, "room_id")
    provider_id = helpers.require_str(data, "provider_id")
    encounter_id = helpers.require_str(data, "encounter_id")
    procedure_kind = helpers.require_enum(data, "procedure_kind", PROCEDURE_KINDS)
    start_at = helpers.require_dt(data, "start_at")
    end_at = helpers.require_dt(data, "end_at")
    expected_room_version = helpers.require_int(data, "expected_room_version")

    # Priority 4: body FK existence.
    room = helpers.get_or_404(db.rooms, room_id, "room")
    provider = helpers.get_or_404(db.providers, provider_id, "provider")
    helpers.get_or_404(db.encounters, encounter_id, "encounter")

    # Priority 5: OCC version check runs before business geometry (PRD 2.7/2.8).
    if expected_room_version != room["version"]:
        raise errors.stale_room_version()

    # Priority 7: MOHS requires MOHS_SUITE room.
    if procedure_kind == "MOHS" and room["room_kind"] != "MOHS_SUITE":
        raise errors.mohs_requires_suite()

    # Priority 8: MOHS requires Mohs-credentialed provider.
    if procedure_kind == "MOHS" and not provider["can_perform_mohs"]:
        raise errors.provider_not_mohs()

    # Priority 9: end_at strictly after start_at.
    if not (end_at > start_at):
        raise errors.invalid_interval()

    # Priority 10: room overlap — half-open window [start, end + buffer).
    buffer = timedelta(minutes=room["turnover_buffer_minutes"])
    for other in db.procedure_bookings.values():
        if other["room_id"] != room_id:
            continue
        if other["status"] not in ("BOOKED", "COMPLETED"):
            continue
        o_start = helpers.parse_dt(other["start_at"])
        o_end = helpers.parse_dt(other["end_at"]) + buffer
        # Half-open [o_start, o_end): overlap iff new.start < o_end and new.end > o_start.
        if start_at < o_end and end_at > o_start:
            raise errors.room_interval_conflict()

    # Priority 10.5: provider double-booking — CLOSED interval [start, end], no buffer.
    for other in db.procedure_bookings.values():
        if other["provider_id"] != provider_id:
            continue
        if other["status"] not in ("BOOKED", "COMPLETED"):
            continue
        o_start = helpers.parse_dt(other["start_at"])
        o_end = helpers.parse_dt(other["end_at"])
        # Closed [o_start, o_end]: overlap iff new.start <= o_end and new.end >= o_start.
        if start_at <= o_end and end_at >= o_start:
            raise errors.provider_double_booked()

    row = {
        "room_id": room_id,
        "provider_id": provider_id,
        "encounter_id": encounter_id,
        "procedure_kind": procedure_kind,
        "start_at": db.iso(start_at),
        "end_at": db.iso(end_at),
        "status": "BOOKED",
    }
    db.stamp_new(row)
    db.procedure_bookings[row["id"]] = row
    # Successful create increments the room's version by one.
    db.touch(room)
    return response.created(row)


@bp.get("/procedure-bookings/<bid>")
@require("FrontDesk", "PracticeAdmin", "Provider")
def get_booking(bid):
    row = helpers.get_or_404(db.procedure_bookings, bid, "booking")
    return response.ok(row)


@bp.get("/procedure-bookings")
@require("FrontDesk", "PracticeAdmin", "Provider")
def list_bookings():
    rows = list(db.procedure_bookings.values())
    for key in ("room_id", "provider_id", "encounter_id"):
        val = request.args.get(key)
        if val is not None:
            rows = [b for b in rows if b[key] == val]
    page, limit, offset, total = helpers.paginate(rows)
    return response.listing(page, limit, offset, total)


@bp.post("/procedure-bookings/<bid>/complete")
@require("Provider")
def complete_booking(bid):
    b = helpers.get_or_404(db.procedure_bookings, bid, "booking")
    if b["status"] != "BOOKED":
        raise errors.bad_state("ERR_BOOKING_BAD_STATE")
    enc = db.encounters.get(b["encounter_id"])
    if enc is None or enc["clinical_status"] != "IN_PROGRESS":
        raise errors.bad_state("ERR_ENCOUNTER_NOT_IN_PROGRESS")
    b["status"] = "COMPLETED"
    db.touch(b)
    return response.ok(b)


@bp.post("/procedure-bookings/<bid>/cancel")
@require("FrontDesk")
def cancel_booking(bid):
    b = helpers.get_or_404(db.procedure_bookings, bid, "booking")
    if b["status"] != "BOOKED":
        raise errors.bad_state("ERR_BOOKING_BAD_STATE")
    b["status"] = "CANCELLED"
    db.touch(b)
    # Cancellation frees the room interval (a cancelled booking no longer
    # participates in overlap checks because of the status filter above).
    return response.ok(b)
