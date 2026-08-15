"""Reservation endpoints: create (OCC + window/overlap/buffer/coverage), checkout, cancel."""

import uuid
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_AIRCRAFT_NOT_AIRWORTHY,
    ERR_GLIDER_OVERLAP,
    ERR_INSTRUCTOR_DOUBLE_BOOKED,
    ERR_INSTRUCTOR_NOT_ACTIVE,
    ERR_INSTRUCTOR_UNAVAILABLE,
    ERR_INVALID_TIME_WINDOW,
    ERR_MEMBER_NOT_ACTIVE,
    ERR_REFERENTIAL_INTEGRITY,
    ERR_RESERVATION_NOT_BOOKED,
    ERR_RESOURCE_NOT_FOUND,
    ERR_STALE_AIRCRAFT_VERSION,
)
from middleware import auth, forbid, require_role
from response import success
from services import (
    CHECKOUT_EARLY_GRACE_MIN,
    INSTRUCTOR_BUFFER_MIN,
    LATE_CANCEL_FEE_CENTS,
    LATE_CANCEL_WINDOW_HOURS,
    currency_ok,
    ser_reservation,
    touch,
)
from util import get_body, need_dt, need_str, paginate, sort_items

bp = Blueprint("reservations", __name__)

ACTIVE_RESERVATION_STATES = ("BOOKED", "CHECKED_OUT")


def _get_reservation_or_404(rid):
    reservation = db.STORE["reservations"].get(rid)
    if reservation is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Reservation not found")
    return reservation


@bp.post("/soaring/reservations")
def create_reservation():
    user_id, role = auth()
    require_role(role, ["Member", "DutyOfficer", "ClubAdmin"])
    body = get_body()
    aircraft_id = need_str(body, "aircraft_id")
    member_id = need_str(body, "member_id")
    instructor_id = body.get("instructor_id")
    if instructor_id is not None and not isinstance(instructor_id, str):
        raise ApiError(ERR_REFERENTIAL_INTEGRITY, 422, "instructor_id must be a string")
    start_at = need_dt(body, "start_at")
    end_at = need_dt(body, "end_at")
    # A Member books for themselves; DutyOfficer/ClubAdmin may book for anyone.
    if role == "Member" and member_id != user_id:
        forbid("A Member may only book reservations for themselves")
    # Existence (path/body references, left to right).
    aircraft = db.STORE["aircraft"].get(aircraft_id)
    if aircraft is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Aircraft not found")
    member = db.STORE["members"].get(member_id)
    if member is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Member not found")
    instructor = None
    if instructor_id is not None:
        instructor = db.STORE["members"].get(instructor_id)
        if instructor is None:
            raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Instructor member not found")
    # OCC: expected_aircraft_version must match the airframe's current version.
    expected = body.get("expected_aircraft_version")
    if (
        isinstance(expected, bool)
        or not isinstance(expected, int)
        or expected != aircraft["version"]
    ):
        raise ApiError(
            ERR_STALE_AIRCRAFT_VERSION, 412,
            "expected_aircraft_version does not match the current Aircraft.version",
        )
    # Member standing.
    if member["status"] != "ACTIVE":
        raise ApiError(
            ERR_MEMBER_NOT_ACTIVE, 409, "The reserving member is not ACTIVE"
        )
    # Window sanity: start_at < end_at and start_at no more than 15 minutes
    # in the past.
    at = db.now()
    if start_at >= end_at or start_at < at - timedelta(minutes=CHECKOUT_EARLY_GRACE_MIN):
        raise ApiError(
            ERR_INVALID_TIME_WINDOW, 422,
            "Reservation window must satisfy start_at < end_at and start_at may "
            "not sit more than 15 minutes in the past",
        )
    # Glider overlap: half-open interval intersection on the same airframe.
    for other in db.STORE["reservations"].values():
        if (
            other["aircraft_id"] == aircraft_id
            and other["status"] in ACTIVE_RESERVATION_STATES
            and other["start_at"] < end_at
            and start_at < other["end_at"]
        ):
            raise ApiError(
                ERR_GLIDER_OVERLAP, 409,
                "Another active reservation overlaps this window on the glider",
            )
    if instructor_id is not None:
        # Instructor double-booking with a 30-minute buffer on either side;
        # a gap of exactly 30 minutes is allowed.
        buffer = timedelta(minutes=INSTRUCTOR_BUFFER_MIN)
        for other in db.STORE["reservations"].values():
            if (
                other.get("instructor_id") == instructor_id
                and other["status"] in ACTIVE_RESERVATION_STATES
                and start_at < other["end_at"] + buffer
                and other["start_at"] < end_at + buffer
            ):
                raise ApiError(
                    ERR_INSTRUCTOR_DOUBLE_BOOKED, 409,
                    "Instructor has another active reservation within 30 minutes",
                )
        # Availability coverage: an OPEN window must fully cover the span.
        covered = False
        for window in db.STORE["availability"].values():
            if (
                window["instructor_id"] == instructor_id
                and window["status"] == "OPEN"
                and window["start_at"] <= start_at
                and window["end_at"] >= end_at
            ):
                covered = True
                break
        if not covered:
            raise ApiError(
                ERR_INSTRUCTOR_UNAVAILABLE, 409,
                "No OPEN availability window of the instructor fully covers "
                "the reservation window",
            )
    # Kind/flag integrity last.
    if aircraft["kind"] != "GLIDER":
        raise ApiError(
            ERR_REFERENTIAL_INTEGRITY, 422,
            "Reservations may only be placed on aircraft of kind GLIDER",
        )
    if instructor_id is not None and not instructor["is_instructor"]:
        raise ApiError(
            ERR_REFERENTIAL_INTEGRITY, 422,
            "instructor_id must reference a member with is_instructor true",
        )
    record = {
        "id": str(uuid.uuid4()),
        "aircraft_id": aircraft_id,
        "member_id": member_id,
        "instructor_id": instructor_id,
        "start_at": start_at,
        "end_at": end_at,
        "status": "BOOKED",
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.STORE["reservations"][record["id"]] = record
    touch(aircraft)  # create increments the airframe's version by one
    return success(ser_reservation(record), "object", 201)


@bp.get("/soaring/reservations")
def list_reservations():
    auth()
    items = list(db.STORE["reservations"].values())
    for param in ("aircraft_id", "member_id", "instructor_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if r.get(param) == value]
    page, meta = paginate(sort_items(items))
    return success([ser_reservation(r) for r in page], "array", 200, meta)


@bp.get("/soaring/reservations/<rid>")
def get_reservation(rid):
    auth()
    return success(ser_reservation(_get_reservation_or_404(rid)), "object", 200)


@bp.post("/soaring/reservations/<rid>/checkout")
def checkout(rid):
    user_id, role = auth()
    require_role(role, ["Member", "DutyOfficer"])
    reservation = _get_reservation_or_404(rid)
    if role == "Member" and reservation["member_id"] != user_id:
        forbid("A Member may only check out their own reservations")
    if reservation["status"] != "BOOKED":
        raise ApiError(
            ERR_RESERVATION_NOT_BOOKED, 409,
            "Checkout requires reservation status BOOKED",
        )
    member = db.STORE["members"].get(reservation["member_id"])
    if member is None or member["status"] != "ACTIVE":
        raise ApiError(ERR_MEMBER_NOT_ACTIVE, 409, "The pilot is not ACTIVE")
    if reservation.get("instructor_id"):
        instructor = db.STORE["members"].get(reservation["instructor_id"])
        if instructor is None or instructor["status"] != "ACTIVE":
            raise ApiError(
                ERR_INSTRUCTOR_NOT_ACTIVE, 409,
                "The assigned instructor is not ACTIVE",
            )
    aircraft = db.STORE["aircraft"].get(reservation["aircraft_id"])
    at = db.now()
    if (
        aircraft is None
        or aircraft["status"] != "AIRWORTHY"
        or not currency_ok(aircraft, at)
    ):
        raise ApiError(
            ERR_AIRCRAFT_NOT_AIRWORTHY, 409,
            "Aircraft is not AIRWORTHY or fails the inline currency check",
        )
    if not (reservation["start_at"] - timedelta(minutes=CHECKOUT_EARLY_GRACE_MIN) <= at <= reservation["end_at"]):
        raise ApiError(
            ERR_INVALID_TIME_WINDOW, 422,
            "Checkout is only available within [start_at - 15min, end_at]",
        )
    reservation["status"] = "CHECKED_OUT"
    touch(reservation)
    return success(ser_reservation(reservation), "object", 200)


@bp.post("/soaring/reservations/<rid>/cancel")
def cancel(rid):
    user_id, role = auth()
    require_role(role, ["Member", "DutyOfficer", "ClubAdmin"])
    reservation = _get_reservation_or_404(rid)
    if role == "Member" and reservation["member_id"] != user_id:
        forbid("A Member may only cancel their own reservations")
    if reservation["status"] != "BOOKED":
        raise ApiError(
            ERR_RESERVATION_NOT_BOOKED, 409,
            "Cancel requires reservation status BOOKED",
        )
    # Endpoint-driven (member-initiated) cancels within the late window post
    # the fee; cascade cancels never reach this handler and never charge.
    at = db.now()
    if reservation["start_at"] - at < timedelta(hours=LATE_CANCEL_WINDOW_HOURS):
        member = db.STORE["members"].get(reservation["member_id"])
        if member is not None:
            member["account_balance_cents"] += LATE_CANCEL_FEE_CENTS
            touch(member)
    reservation["status"] = "CANCELLED"
    touch(reservation)
    return success(ser_reservation(reservation), "object", 200)
