"""Operating-room and surgeon bookings (PRD 3.6, priorities 18-19)."""

from datetime import timedelta

from flask import Blueprint, g

import calc
import domain
import serialize
from db import db, new_entity, touch
from errors import ApiError
from middleware import ALL_ROLES, authenticate
from response import list_response, object_response
from routes.chains import find_segment
from routes.programs import find_room, find_staff
from util import whole_minutes
from validation import get_body, pagination, q_enum, q_str, req_dt, req_enum, req_str

bp = Blueprint("bookings", __name__)


def find_booking(booking_id):
    booking = db.bookings.get(booking_id)
    if booking is None:
        raise ApiError(
            "ERR_BOOKING_NOT_FOUND", "no ProcedureBooking with id %s" % booking_id
        )
    return booking


@bp.post("/procedure-bookings")
def create_booking():
    authenticate(["TransplantCoordinator"])
    body = get_body()
    operating_room_id = req_str(body, "operating_room_id")
    chain_segment_id = req_str(body, "chain_segment_id")
    surgeon_staff_id = req_str(body, "surgeon_staff_id")
    booking_role = req_enum(body, "booking_role", calc.BOOKING_ROLES)
    start_at = req_dt(body, "start_at")
    end_at = req_dt(body, "end_at")
    if end_at <= start_at:
        raise ApiError("ERR_VALIDATION", "end_at must be later than start_at")

    # priority 5 -- body FK existence, left to right
    room = find_room(operating_room_id)
    segment = find_segment(chain_segment_id)
    surgeon = find_staff(surgeon_staff_id)

    # priority 10 -- the booked surgeon must actually be an active surgeon
    if surgeon["staff_role"] != "SURGEON" or not surgeon["is_active"]:
        raise ApiError(
            "ERR_STAFF_ROLE_INVALID", "the named staff member is not an active SURGEON"
        )

    # priority 15 -- single-program containment
    chain = domain.chain_of_segment(segment)
    domain.require_same_program(
        [
            room["program_id"],
            chain["program_id"] if chain is not None else None,
            surgeon["program_id"],
            g.staff["program_id"] if g.staff is not None else None,
        ]
    )

    # priority 18 -- room occupancy, half-open windows padded by the turnover buffer
    buffer_minutes = timedelta(minutes=room["turnover_buffer_minutes"])
    for existing in domain.bookings_of_room(room):
        if existing["status"] != "ACTIVE":
            continue
        if start_at < existing["end_at"] + buffer_minutes and (
            end_at + buffer_minutes > existing["start_at"]
        ):
            raise ApiError(
                "ERR_OR_SLOT_CONFLICT",
                "the room is already occupied inside its turnover buffer",
            )

    # priority 19 -- surgeon availability, closed intervals and no buffer at all
    for existing in domain.bookings_of_surgeon(surgeon["id"]):
        if existing["status"] != "ACTIVE":
            continue
        if start_at <= existing["end_at"] and end_at >= existing["start_at"]:
            raise ApiError(
                "ERR_SURGEON_DOUBLE_BOOKED", "the surgeon is already booked for this interval"
            )

    row = new_entity(
        "ProcedureBooking",
        {
            "operating_room_id": room["id"],
            "chain_segment_id": segment["id"],
            "surgeon_staff_id": surgeon["id"],
            "booking_role": booking_role,
            "start_at": start_at,
            "end_at": end_at,
            "status": "ACTIVE",
            "duration_minutes": whole_minutes(start_at, end_at),
            "cancel_reason_code": None,
        },
    )
    db.bookings[row["id"]] = row
    return object_response(serialize.procedure_booking(row), 201)


@bp.post("/procedure-bookings/<booking_id>/cancellation")
def cancel_booking(booking_id):
    authenticate(["TransplantCoordinator"])
    booking = find_booking(booking_id)

    body = get_body()
    cancel_reason_code = req_str(body, "cancel_reason_code")

    # priority 9 -- the domain-specific code wins over the generic terminal rule
    if booking["status"] != "ACTIVE":
        raise ApiError(
            "ERR_BOOKING_NOT_ACTIVE", "a booking in %s may not be cancelled" % booking["status"]
        )

    segment = db.segments.get(booking["chain_segment_id"])
    if segment is not None and segment["status"] == "TRANSPLANTED":
        raise ApiError(
            "ERR_INVALID_STATE_TRANSITION",
            "the booking's segment has already been transplanted",
        )

    booking["status"] = "CANCELLED"
    booking["cancel_reason_code"] = cancel_reason_code
    touch(booking)
    return object_response(serialize.procedure_booking(booking))


@bp.get("/procedure-bookings")
def list_bookings():
    authenticate(ALL_ROLES)
    operating_room_id = q_str("operating_room_id")
    chain_segment_id = q_str("chain_segment_id")
    surgeon_staff_id = q_str("surgeon_staff_id")
    booking_role = q_enum("booking_role", calc.BOOKING_ROLES)
    status = q_enum("status", calc.BOOKING_STATUSES)
    limit, offset = pagination()

    rows = list(db.bookings.values())
    if operating_room_id is not None:
        rows = [r for r in rows if r["operating_room_id"] == operating_room_id]
    if chain_segment_id is not None:
        rows = [r for r in rows if r["chain_segment_id"] == chain_segment_id]
    if surgeon_staff_id is not None:
        rows = [r for r in rows if r["surgeon_staff_id"] == surgeon_staff_id]
    if booking_role is not None:
        rows = [r for r in rows if r["booking_role"] == booking_role]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_response([serialize.procedure_booking(r) for r in page], limit, offset, total)


@bp.get("/procedure-bookings/<booking_id>")
def get_booking(booking_id):
    authenticate(ALL_ROLES)
    booking = find_booking(booking_id)
    return object_response(serialize.procedure_booking(booking))
