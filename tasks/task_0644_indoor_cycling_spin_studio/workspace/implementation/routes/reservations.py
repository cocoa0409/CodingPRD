"""Reservation endpoints (PRD §3.4, §3.5, §3.7).

Booking validation ladder (PRD §3.4, ordering is load-bearing):
  auth -> role -> existence/scope -> ownership -> session state ->
  OCC (expected_session_version) -> member ACTIVE (not suspended) ->
  bike available -> duplicate reservation -> chargeable pack ->
  capacity (session full) -> body validation.
"""
from flask import Blueprint, request

from clock import clock
from datetime import timedelta
from constants import (
    ROLE_STUDIO_MANAGER, ROLE_MEMBER, ROLE_INSTRUCTOR, CHECKIN_OPEN_MINUTES,
)
from db import db, stamp_new, touch
from errors import (
    err, ERR_VALIDATION, ERR_OWNERSHIP_VIOLATION, ERR_INVALID_STATE,
    ERR_STALE_SESSION_VERSION, ERR_MEMBER_SUSPENDED, ERR_BIKE_UNAVAILABLE,
    ERR_DUPLICATE_RESERVATION, ERR_NO_CHARGEABLE_PACK, ERR_SESSION_FULL,
    ERR_WINDOW_CLOSED, ERR_PARENT_RESERVATION_NOT_ATTENDED, ERR_NOT_FOUND,
)
from middleware import require_auth, require_role
from response import success_object, success_array
from serializers import reservation_out
from services import lookup, validate, paging, booking
from services import packs as pack_svc

bp = Blueprint("reservations", __name__)

READ_ROLES = {ROLE_STUDIO_MANAGER, ROLE_MEMBER, ROLE_INSTRUCTOR}


@bp.route("/studios/<studio_id>/sessions/<session_id>/reservations", methods=["POST"])
def create_reservation(studio_id, session_id):
    # auth -> role
    user_id, role = require_auth()
    require_role(role, {ROLE_MEMBER})
    # existence + scope (left to right): studio, session-in-studio
    session = lookup.get_session_in_studio(studio_id, session_id)
    # body
    body = validate.get_body()
    member_id = validate.require_str(body, "member_id")
    bike_id = validate.require_str(body, "bike_id")
    expected_version = validate.require_int(body, "expected_session_version")
    shoe_size = validate.opt_number(body, "shoe_size", None)
    if shoe_size is not None and shoe_size <= 0:
        raise err(ERR_VALIDATION, "shoe_size must be positive")

    # member must exist (existence)
    member = lookup.get_member(member_id)
    # ownership: acting member books only for themselves
    if user_id != member_id:
        raise err(ERR_OWNERSHIP_VIOLATION, "Members may only book for themselves")

    # session state valid for booking
    if session["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Session is not SCHEDULED")

    # OCC: expected_session_version
    if expected_version != session["version"]:
        raise err(ERR_STALE_SESSION_VERSION, "expected_session_version does not match current version")

    # member ACTIVE (not suspended)
    if member["account_status"] != "ACTIVE":
        raise err(ERR_MEMBER_SUSPENDED, "Suspended members cannot book")

    # bike must be ACTIVE, belong to the session's room, and not already held.
    bike = db.bikes.get(bike_id)
    if bike is None or bike["room_id"] != session["room_id"]:
        # Per PRD §2.5 a bike chosen for a reservation must belong to the
        # session's room; otherwise it does not exist within scope.
        raise err(ERR_BIKE_UNAVAILABLE, "Chosen bike is unavailable")
    if bike["status"] != "ACTIVE":
        raise err(ERR_BIKE_UNAVAILABLE, "Chosen bike is not ACTIVE")
    if booking.bike_held(session_id, bike_id):
        raise err(ERR_BIKE_UNAVAILABLE, "Bike already held by a BOOKED reservation")

    # duplicate reservation: member already has a BOOKED seat on this session
    if booking.member_has_booked(session_id, member_id):
        raise err(ERR_DUPLICATE_RESERVATION, "Member already has a BOOKED reservation on this session")

    # chargeable pack / first-ride comp
    first_ride = booking.first_ride_eligible(member)
    chosen_pack = None
    if not first_ride:
        chosen_pack = booking.select_chargeable_pack(member, session)
        if chosen_pack is None:
            raise err(ERR_NO_CHARGEABLE_PACK, "No chargeable pack covering this session")

    # capacity: rejected when booked_count >= capacity
    if booking.booked_count(session_id) >= session["capacity"]:
        raise err(ERR_SESSION_FULL, "Session is full; join the waitlist")

    # ----- commit -----
    credit_pack_id = None
    if first_ride:
        credit_pack_id = None
    else:
        credit_pack_id = chosen_pack["id"]
        pack_svc.debit_one(chosen_pack)

    rec = booking._create_reservation(session, member, bike_id, shoe_size, credit_pack_id, first_ride)
    touch(session)  # version bump + booked_count recompute
    return success_object(reservation_out(rec), 201)


@bp.route("/reservations/<reservation_id>", methods=["GET"])
def get_reservation(reservation_id):
    user_id, role = require_auth()
    require_role(role, READ_ROLES)
    rec = lookup.get_reservation(reservation_id)
    if role == ROLE_MEMBER and user_id != rec["member_id"]:
        raise err(ERR_OWNERSHIP_VIOLATION, "Members may only read their own reservations")
    return success_object(reservation_out(rec), 200)


@bp.route("/reservations", methods=["GET"])
def list_reservations():
    user_id, role = require_auth()
    require_role(role, READ_ROLES)
    limit, offset = paging.get_pagination()
    f_session = request.args.get("session_id")
    f_member = request.args.get("member_id")
    f_bike = request.args.get("bike_id")
    f_pack = request.args.get("credit_pack_id")
    records = []
    for r in db.reservations.values():
        if f_session is not None and r["session_id"] != f_session:
            continue
        if f_member is not None and r["member_id"] != f_member:
            continue
        if f_bike is not None and r["bike_id"] != f_bike:
            continue
        if f_pack is not None and r["credit_pack_id"] != f_pack:
            continue
        if role == ROLE_MEMBER and r["member_id"] != user_id:
            continue
        records.append(r)
    records = paging.sort_default(records)
    page, total = paging.apply_page(records, limit, offset)
    return success_array([reservation_out(r) for r in page], limit, offset, total)


@bp.route("/studios/<studio_id>/sessions/<session_id>/reservations/<reservation_id>/cancel", methods=["POST"])
def cancel_reservation(studio_id, session_id, reservation_id):
    user_id, role = require_auth()
    require_role(role, {ROLE_MEMBER})
    res = lookup.get_reservation_in_session(studio_id, session_id, reservation_id)
    session = db.sessions[session_id]
    studio = db.studios[session["studio_id"]]

    # ownership
    if user_id != res["member_id"]:
        raise err(ERR_OWNERSHIP_VIOLATION, "Members may only cancel their own reservations")

    # state: reservation must be BOOKED and session SCHEDULED
    if res["attendance_status"] != "BOOKED" or session["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Reservation cannot be cancelled in its current state")

    # timing window
    now = clock.now()
    if now >= session["start_utc"]:
        raise err(ERR_WINDOW_CLOSED, "Cannot cancel at or after session start")

    boundary = session["start_utc"] - timedelta(minutes=studio["late_cancel_window_minutes"])
    if now <= boundary:
        booking.early_cancel(res, session, studio)
    else:
        booking.late_cancel(res, session, studio)
    return success_object(reservation_out(res), 200)


@bp.route("/studios/<studio_id>/sessions/<session_id>/reservations/<reservation_id>/check-in", methods=["POST"])
def check_in_reservation(studio_id, session_id, reservation_id):
    user_id, role = require_auth()
    require_role(role, {ROLE_INSTRUCTOR})
    res = lookup.get_reservation_in_session(studio_id, session_id, reservation_id)
    session = db.sessions[session_id]

    # ownership: instructor may only act on sessions they teach
    if session["instructor_id"] != user_id:
        raise err(ERR_OWNERSHIP_VIOLATION, "Instructor does not teach this session")

    # state: reservation BOOKED and session SCHEDULED
    if res["attendance_status"] != "BOOKED" or session["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Reservation cannot be checked in")

    # window: start_utc - CHECKIN_OPEN_MINUTES <= now <= end_utc
    now = clock.now()
    open_at = session["start_utc"] - timedelta(minutes=CHECKIN_OPEN_MINUTES)
    if now < open_at or now > session["end_utc"]:
        raise err(ERR_WINDOW_CLOSED, "Check-in window is closed")

    booking.check_in(res, session)
    return success_object(reservation_out(res), 200)


@bp.route("/reservations/<reservation_id>/return-shoe", methods=["POST"])
def return_shoe(reservation_id):
    user_id, role = require_auth()
    require_role(role, {ROLE_INSTRUCTOR})
    res = lookup.get_reservation(reservation_id)
    session = db.sessions.get(res["session_id"])

    # ownership: instructor teaches the session
    if session is None or session["instructor_id"] != user_id:
        raise err(ERR_OWNERSHIP_VIOLATION, "Instructor does not teach this reservation's session")

    # shoe must be RESERVED
    if res["shoe_status"] != "RESERVED":
        raise err(ERR_INVALID_STATE, "Shoe is not RESERVED")
    # reservation must be ATTENDED
    if res["attendance_status"] != "ATTENDED":
        raise err(ERR_PARENT_RESERVATION_NOT_ATTENDED, "Reservation is not ATTENDED")

    res["shoe_status"] = "RETURNED"
    touch(res)
    return success_object(reservation_out(res), 200)
