"""Combine bookings: creation, conflict detection and the status machine
(PRD 3.3)."""

from flask import Blueprint

import auth
import constants as K
import derive
import logic
import respond
import validate
from db import db
from errors import ApiError
from timeutil import add_minutes

bp = Blueprint("bookings", __name__)

READ_ROLES = [
    "LeagueDraftAdmin",
    "ClubGM",
    "CombineMedicalExaminer",
    "ProspectAgent",
]


def _shape_error():
    raise ApiError(
        "ERR_BOOKING_RESOURCE_MISMATCH",
        "The supplied resource fields do not match the booking type.",
    )


@bp.post("/combine-bookings")
def create_booking():
    auth.begin(["LeagueDraftAdmin"])
    data = validate.body()
    prospect_id = validate.string(data, "prospect_id")
    booking_type = validate.enum(data, "booking_type", K.BOOKING_TYPES)
    starts_at = validate.instant(data, "starts_at")
    ends_at = validate.instant(data, "ends_at")
    station_id = validate.string(data, "medical_station_id", required=False)
    room_id = validate.string(data, "interview_room_id", required=False)
    club_id = validate.string(data, "club_id", required=False)
    if ends_at <= starts_at:
        validate.bad("ends_at must be strictly after starts_at.")

    # rule 5 -- foreign keys in declared input order
    prospect = logic.fk_lookup(db.prospects, prospect_id, "prospect")
    station = None
    room = None
    club = None
    if station_id is not None:
        station = logic.fk_lookup(db.medical_stations, station_id, "medical station")
    if room_id is not None:
        room = logic.fk_lookup(db.interview_rooms, room_id, "interview room")
    if club_id is not None:
        club = logic.fk_lookup(db.clubs, club_id, "club")

    cycle = derive.prospect_cycle(prospect)
    logic.require_phase(cycle, ("COMBINE_WEEK",))
    logic.require_unfrozen(cycle)

    # rule 17 -- combine-week containment
    if starts_at < cycle["combine_week_start_at"] or ends_at > cycle["combine_week_end_at"]:
        raise ApiError(
            "ERR_OUTSIDE_COMBINE_WEEK",
            "The interval does not sit wholly inside the combine week.",
        )

    # rule 20 -- cycle cohesion
    if club is not None:
        logic.require_same_cycle(club["draft_cycle_id"], cycle["id"])

    # rule 21 -- resource shape
    if booking_type == "MEDICAL_EXAM":
        if station is None or room is not None or club is not None:
            _shape_error()
    elif booking_type == "CLUB_INTERVIEW":
        if room is None or club is None or station is not None:
            _shape_error()
    else:  # ON_FIELD_TEST
        if station is not None or room is not None or club is not None:
            _shape_error()

    # rules 32, 33, 34
    if station is not None:
        logic.check_station_conflict(station, starts_at, ends_at)
    if room is not None:
        logic.check_room_capacity(room, starts_at, ends_at)
    logic.check_itinerary(prospect["id"], starts_at, ends_at)

    rec = db.insert(
        db.combine_bookings,
        "CombineBooking",
        {
            "prospect_id": prospect["id"],
            "booking_type": booking_type,
            "medical_station_id": station["id"] if station is not None else None,
            "interview_room_id": room["id"] if room is not None else None,
            "club_id": club["id"] if club is not None else None,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "status": "SCHEDULED",
            "duration_minutes": logic.duration_minutes(starts_at, ends_at),
        },
    )
    return respond.created(rec)


@bp.get("/combine-bookings/<booking_id>")
def get_booking(booking_id):
    auth.begin(READ_ROLES)
    return respond.one(logic.path_lookup(db.combine_bookings, booking_id))


@bp.get("/combine-bookings")
def list_bookings():
    auth.begin(READ_ROLES)
    limit, offset = validate.pagination()
    prospect_id = validate.query_str("prospect_id")
    station_id = validate.query_str("medical_station_id")
    room_id = validate.query_str("interview_room_id")
    club_id = validate.query_str("club_id")
    booking_type = validate.query_enum("booking_type", K.BOOKING_TYPES)
    status = validate.query_enum("status", K.BOOKING_STATUSES)

    rows = list(db.combine_bookings.values())
    if prospect_id is not None:
        rows = [r for r in rows if r["prospect_id"] == prospect_id]
    if station_id is not None:
        rows = [r for r in rows if r["medical_station_id"] == station_id]
    if room_id is not None:
        rows = [r for r in rows if r["interview_room_id"] == room_id]
    if club_id is not None:
        rows = [r for r in rows if r["club_id"] == club_id]
    if booking_type is not None:
        rows = [r for r in rows if r["booking_type"] == booking_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return respond.listing(logic.by_starts_at(rows), limit, offset)


@bp.post("/combine-bookings/<booking_id>/status")
def booking_status(booking_id):
    auth.begin(["LeagueDraftAdmin"])
    data = validate.body()
    action = validate.enum(
        data, "action", ("CHECK_IN", "COMPLETE", "CANCEL", "MARK_NO_SHOW")
    )
    booking = logic.path_lookup(db.combine_bookings, booking_id)
    prospect = db.prospects.get(booking["prospect_id"])
    cycle = derive.prospect_cycle(prospect) if prospect is not None else None

    if action == "CHECK_IN" and cycle is not None:
        logic.require_phase(cycle, ("COMBINE_WEEK",))
    if cycle is not None:
        logic.require_unfrozen(cycle)

    current = booking["status"]
    if action == "CHECK_IN":
        if current != "SCHEDULED":
            raise logic.invalid_transition("Only a SCHEDULED booking may check in.")
        earliest = add_minutes(booking["starts_at"], -K.BOOKING_CHECKIN_LEAD_MINUTES)
        if db.now < earliest:
            raise logic.invalid_transition(
                "A prospect may present at most thirty minutes early."
            )
        booking["status"] = "CHECKED_IN"
    elif action == "COMPLETE":
        if current != "CHECKED_IN":
            raise logic.invalid_transition(
                "Only a CHECKED_IN booking may be completed."
            )
        booking["status"] = "COMPLETED"
    elif action == "CANCEL":
        if current != "SCHEDULED":
            raise logic.invalid_transition("Only a SCHEDULED booking may be cancelled.")
        booking["status"] = "CANCELLED"
    else:  # MARK_NO_SHOW
        if current not in K.BOOKING_ACTIVE_STATUSES:
            raise logic.invalid_transition(
                "Only a SCHEDULED or CHECKED_IN booking may be marked no-show."
            )
        if db.now < booking["ends_at"]:
            raise logic.invalid_transition(
                "A no-show may only be recorded once the slot has ended."
            )
        booking["status"] = "NO_SHOW"
        if booking["booking_type"] == "MEDICAL_EXAM" and prospect is not None:
            prospect["medical_clearance_status"] = "UNVERIFIED"
    return respond.ok(booking)
