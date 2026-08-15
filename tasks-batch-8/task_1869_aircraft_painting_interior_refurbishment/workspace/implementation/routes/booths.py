"""PaintBooth and BoothBooking endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import calc
from db import STORE
from domain import (new_entity, bump, bump_program, get_or_404, by_created,
                    serialize_booth, serialize_booking)
from errors import (ApiError, ref_integrity, invalid_state,
                    ERR_BOOTH_BUFFER_VIOLATION)
from middleware import auth
from response import success
from validation import get_body, field, paginate

bp = Blueprint("booths", __name__)

BOOKABLE_PHASES = ("QUOTED", "BOOKED", "INDUCTED", "SURFACE_REVIEW", "IN_WORK")


@bp.post("/paint-booths")
def create_booth():
    auth("CenterAdmin")
    data = get_body(required=True)
    name = field(data, "name", "str")
    hourly_rate_cents = field(data, "hourly_rate_cents", "int")
    cure_buffer_hours = field(data, "cure_buffer_hours", "int")
    booth = new_entity()
    booth.update({
        "name": name,
        "hourly_rate_cents": hourly_rate_cents,
        "cure_buffer_hours": cure_buffer_hours,
    })
    STORE.paint_booths[booth["id"]] = booth
    return success(serialize_booth(booth), status=201)


@bp.get("/paint-booths")
def list_booths():
    auth()
    items = by_created(list(STORE.paint_booths.values()))
    return paginate(items, serialize_booth)


@bp.post("/booth-bookings")
def create_booking():
    auth("ProgramManager")
    data = get_body(required=True)
    booth_id = field(data, "booth_id", "str")
    program_id = field(data, "program_id", "str")
    start_at = field(data, "start_at", "datetime")
    end_at = field(data, "end_at", "datetime")
    booth = STORE.paint_booths.get(booth_id)
    if booth is None:
        raise ref_integrity("booth_id does not reference an existing paint booth")
    prog = STORE.programs.get(program_id)
    if prog is None:
        raise ref_integrity("program_id does not reference an existing program")
    if prog["status"] not in BOOKABLE_PHASES:
        raise invalid_state(
            "Booth bookings require the program to be QUOTED through IN_WORK")
    buffer = timedelta(hours=booth["cure_buffer_hours"])
    for b in STORE.booth_bookings.values():
        if b["booth_id"] != booth_id or b["status"] not in ("BOOKED", "COMPLETED"):
            continue
        # Buffer-gap rule (symmetric): gap exactly equal to the buffer is legal.
        if not (start_at >= b["end_at"] + buffer or end_at + buffer <= b["start_at"]):
            raise ApiError(ERR_BOOTH_BUFFER_VIOLATION, 409,
                           "Booking leaves less than the cure buffer around an "
                           "existing booking")
    booking = new_entity()
    booking.update({
        "booth_id": booth_id,
        "program_id": program_id,
        "start_at": start_at,
        "end_at": end_at,
        "status": "BOOKED",
        "actual_hours": None,
        "scheduled_fee_cents": None,
        "actual_fee_cents": None,
    })
    booking["scheduled_fee_cents"] = calc.scheduled_fee(booking, booth)
    STORE.booth_bookings[booking["id"]] = booking
    return success(serialize_booking(booking), status=201)


@bp.get("/booth-bookings/<bid>")
def get_booking(bid):
    auth()
    booking = get_or_404(STORE.booth_bookings, bid, "BoothBooking")
    return success(serialize_booking(booking))


@bp.get("/booth-bookings")
def list_bookings():
    auth()
    items = by_created(list(STORE.booth_bookings.values()))
    for key in ("booth_id", "program_id", "status"):
        value = request.args.get(key)
        if value is not None:
            items = [b for b in items if b[key] == value]
    return paginate(items, serialize_booking)


@bp.post("/booth-bookings/<bid>/complete")
def complete_booking(bid):
    auth("ShopTechnician")
    data = get_body(required=True)
    actual_hours = field(data, "actual_hours", "int")
    booking = get_or_404(STORE.booth_bookings, bid, "BoothBooking")
    if booking["status"] != "BOOKED":
        raise invalid_state("Only a BOOKED booking can be completed")
    prog = STORE.programs[booking["program_id"]]
    if prog["status"] != "IN_WORK":
        raise invalid_state("Booth completion requires the program to be IN_WORK")
    booth = STORE.paint_booths[booking["booth_id"]]
    booking["actual_hours"] = actual_hours
    booking["actual_fee_cents"] = calc.actual_fee(booking, booth, actual_hours)
    booking["status"] = "COMPLETED"
    bump(booking)
    bump_program(prog)
    return success(serialize_booking(booking))


@bp.post("/booth-bookings/<bid>/cancel")
def cancel_booking(bid):
    auth("ProgramManager")
    booking = get_or_404(STORE.booth_bookings, bid, "BoothBooking")
    if booking["status"] != "BOOKED":
        raise invalid_state("Only a BOOKED booking can be cancelled")
    booking["status"] = "CANCELLED"
    bump(booking)
    return success(serialize_booking(booking))
