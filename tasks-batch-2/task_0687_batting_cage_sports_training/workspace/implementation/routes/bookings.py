"""Booking routes — the central temporal entity (PRD 3.4-3.7).

Validation order (PRD 2.11) for confirm:
  5  state          ERR_INVALID_STATE
  6  waiver          ERR_WAIVER_REQUIRED
  7  posture         ERR_FACILITY_POSTURE_BLOCK
  8  strikes         ERR_TOO_MANY_STRIKES
  9  resource avail  ERR_RESOURCE_UNAVAILABLE
  *  OCC stale lane  ERR_STALE_LANE_VERSION  (PRD 2.8: BEFORE the overlap test)
 10  lane conflict   ERR_LANE_TIME_CONFLICT
 11  open hours      ERR_OUTSIDE_HOURS
 12  booking shape   ERR_BOOKING_SHAPE_INVALID
 13  funds/minutes   ERR_INSUFFICIENT_FUNDS
"""
from flask import Blueprint, request

from clock import clock, parse_iso
from constants import (
    SLOT_MINUTES,
    MAX_STRIKES,
    MEMBER_MINUTE_CAP,
    EARLY_CHECKIN_MIN,
    PITCHES_PER_SESSION,
)
from datetime import timedelta
from db import db
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_FORBIDDEN_ROLE,
    ERR_WAIVER_REQUIRED,
    ERR_FACILITY_POSTURE_BLOCK,
    ERR_TOO_MANY_STRIKES,
    ERR_RESOURCE_UNAVAILABLE,
    ERR_LANE_TIME_CONFLICT,
    ERR_OUTSIDE_HOURS,
    ERR_BOOKING_SHAPE_INVALID,
    ERR_INSUFFICIENT_FUNDS,
    ERR_STALE_LANE_VERSION,
)
from helpers import (
    get_json_body,
    require_fields,
    require_enum,
    lookup,
    base_common_fields,
    parse_pagination,
    paginate,
)
from middleware import authenticate, require_role
from response import success
from serializers import booking_out
from services import pricing
from services.booking_ops import (
    occupied_lane_ids,
    booking_conflicts_on_lane,
    cancel_booking,
)
from services.derive import recompute_machine, recompute_member_waiver, touch

bp = Blueprint("bookings", __name__)

READ_ROLES = ["FacilityManager", "FrontDesk", "Member", "Instructor"]
BOOKING_KINDS = {"OPEN_SLOT", "LESSON", "TEAM_BLOCK", "PARTY"}
PAY_MODES = {"TOKEN", "HOURLY", "MEMBERSHIP"}


def _minute_of_day(dt):
    return dt.hour * 60 + dt.minute


def _interval_within_hours(facility, start, end):
    """PRD 3.4/3.5: interval must fall within [open_minute, close_minute) on its day.

    The interval is bounded by the facility's daily open window. We require both
    endpoints to fall within the day's window: start at/after open_minute and end
    at/before close_minute (end is exclusive of close so end_minute <= close_minute),
    and the interval must not span a day boundary.
    """
    if start.date() != (end - timedelta(microseconds=1)).date():
        # Spans across midnight day boundary -> outside a single day's hours.
        if start.date() != end.date():
            return False
    start_min = _minute_of_day(start)
    end_min = _minute_of_day(end)
    if end_min == 0:
        # end exactly at midnight -> treat as 1440 for same-day end.
        end_min = 1440
    if start_min < facility["open_minute"]:
        return False
    if end_min > facility["close_minute"]:
        return False
    return True


# ---------------------------------------------------------------------------
# POST /v1/bookings — request (forward-looking quote)
# ---------------------------------------------------------------------------
@bp.post("/v1/bookings")
def request_booking():
    user_id, role = authenticate()
    require_role(role, ["Member", "FrontDesk"])
    body = get_json_body()
    require_fields(body, ["facility_id", "lane_id", "member_id", "kind", "pay_mode",
                          "start_utc", "end_utc"])

    # Existence (priority 3), left-to-right.
    facility = lookup(db.facilities, body["facility_id"])
    lane = lookup(db.lanes, body["lane_id"])
    if lane["facility_id"] != facility["id"]:
        raise err(ERR_NOT_FOUND, "Lane not in facility scope")
    member = lookup(db.members, body["member_id"])
    if member["facility_id"] != facility["id"]:
        raise err(ERR_NOT_FOUND, "Member not in facility scope")

    instructor = None
    if body.get("instructor_id") is not None:
        instructor = lookup(db.instructors, body["instructor_id"])
        if instructor["facility_id"] != facility["id"]:
            raise err(ERR_NOT_FOUND, "Instructor not in facility scope")
    machine = None
    if body.get("machine_id") is not None:
        machine = lookup(db.machines, body["machine_id"])
        if machine["facility_id"] != facility["id"]:
            raise err(ERR_NOT_FOUND, "Machine not in facility scope")

    team_lane_ids = body.get("team_lane_ids", []) or []
    if not isinstance(team_lane_ids, list):
        raise err(ERR_INVALID_REQUEST, "team_lane_ids must be a list")
    for tl in team_lane_ids:
        tlane = lookup(db.lanes, tl)
        if tlane["facility_id"] != facility["id"]:
            raise err(ERR_NOT_FOUND, "Team lane not in facility scope")

    # Member acting on self (PRD 2.1).
    if role == "Member" and user_id != body["member_id"]:
        raise err(ERR_FORBIDDEN_ROLE, "Members may only book for themselves")

    # Well-formedness (priority 4).
    require_enum(body["kind"], BOOKING_KINDS, "kind")
    require_enum(body["pay_mode"], PAY_MODES, "pay_mode")

    try:
        start = parse_iso(body["start_utc"])
        end = parse_iso(body["end_utc"])
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "Invalid datetime")
    if end <= start:
        raise err(ERR_INVALID_REQUEST, "end_utc must be after start_utc")
    duration_minutes = int((end - start).total_seconds() // 60)
    if duration_minutes <= 0 or duration_minutes % SLOT_MINUTES != 0:
        raise err(ERR_INVALID_REQUEST, "duration must be a positive multiple of slot length")

    lane_count = body.get("lane_count", 1)
    if not isinstance(lane_count, int) or isinstance(lane_count, bool) or lane_count < 1:
        raise err(ERR_INVALID_REQUEST, "lane_count must be >= 1")
    if lane_count != 1 + len(team_lane_ids):
        raise err(ERR_INVALID_REQUEST, "lane_count must equal 1 + len(team_lane_ids)")

    party_guests = body.get("party_guests", 0)
    if not isinstance(party_guests, int) or isinstance(party_guests, bool) or party_guests < 0:
        raise err(ERR_INVALID_REQUEST, "party_guests must be >= 0")

    booking = base_common_fields()
    booking.update({
        "facility_id": body["facility_id"],
        "lane_id": body["lane_id"],
        "member_id": body["member_id"],
        "instructor_id": body.get("instructor_id"),
        "machine_id": body.get("machine_id"),
        "kind": body["kind"],
        "pay_mode": body["pay_mode"],
        "lane_count": lane_count,
        "team_lane_ids": team_lane_ids,
        "party_guests": party_guests,
        "start_utc": body["start_utc"],
        "end_utc": body["end_utc"],
        "duration_minutes": duration_minutes,
        "final_cost_cents": 0,
        "token_cost": 0,
        "status": "REQUESTED",
    })

    # At request time: resource availability (priority 9) and booking shape (12)
    # and open hours (11) are checked (PRD 3.4).
    _check_resource_available(booking, facility, machine)
    _check_booking_shape(booking, instructor, member)
    if not _interval_within_hours(facility, start, end):
        raise err(ERR_OUTSIDE_HOURS, "Booking interval outside facility open hours")

    # Forward-looking quote.
    booking["quoted_cost_cents"] = pricing.quote_cost(
        booking, lane, facility, member, instructor, machine
    )

    db.bookings[booking["id"]] = booking
    return success(booking_out(booking), status=201)


def _occupied_lanes(booking):
    return [db.lanes[lid] for lid in occupied_lane_ids(booking) if lid in db.lanes]


def _check_resource_available(booking, facility, machine):
    """Priority 9: machine not OUT_OF_SERVICE; lane(s) maint_status AVAILABLE."""
    if machine is not None and machine["status"] == "OUT_OF_SERVICE":
        raise err(ERR_RESOURCE_UNAVAILABLE, "Machine is OUT_OF_SERVICE")
    for lane in _occupied_lanes(booking):
        if lane["maint_status"] != "AVAILABLE":
            raise err(ERR_RESOURCE_UNAVAILABLE, "Lane not AVAILABLE for the interval")


def _check_booking_shape(booking, instructor, member):
    """Priority 12: LESSON needs active instructor; MEMBERSHIP needs tier != NONE;
    PARTY needs party_guests >= 1."""
    if booking["kind"] == "LESSON":
        if instructor is None or not instructor["active"]:
            raise err(ERR_BOOKING_SHAPE_INVALID, "LESSON requires an active instructor")
    if booking["pay_mode"] == "MEMBERSHIP" and member["tier"] == "NONE":
        raise err(ERR_BOOKING_SHAPE_INVALID, "MEMBERSHIP requires a non-NONE tier")
    if booking["kind"] == "PARTY" and booking["party_guests"] < 1:
        raise err(ERR_BOOKING_SHAPE_INVALID, "PARTY requires at least one guest")


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------
@bp.get("/v1/bookings/<booking_id>")
def get_booking(booking_id):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    booking = lookup(db.bookings, booking_id)
    return success(booking_out(booking), status=200)


@bp.get("/v1/bookings")
def list_bookings():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    args = request.args
    facility_id = args.get("facility_id")
    lane_id = args.get("lane_id")
    member_id = args.get("member_id")
    instructor_id = args.get("instructor_id")
    machine_id = args.get("machine_id")
    team_lane = args.get("team_lane_ids")
    status = args.get("status")

    def matches(b):
        if facility_id is not None and b["facility_id"] != facility_id:
            return False
        # lane_id matches primary OR any team lane (PRD: a team lane appears when
        # lane_id matches any occupied lane).
        if lane_id is not None and lane_id not in occupied_lane_ids(b):
            return False
        if member_id is not None and b["member_id"] != member_id:
            return False
        if instructor_id is not None and b["instructor_id"] != instructor_id:
            return False
        if machine_id is not None and b["machine_id"] != machine_id:
            return False
        if team_lane is not None and team_lane not in (b.get("team_lane_ids") or []):
            return False
        if status is not None and b["status"] != status:
            return False
        return True

    items = [b for b in db.bookings.values() if matches(b)]
    page, meta = paginate(items, limit, offset)
    return success([booking_out(b) for b in page], status=200, pagination=meta)


# ---------------------------------------------------------------------------
# POST /v1/bookings/{id}/confirm
# ---------------------------------------------------------------------------
@bp.post("/v1/bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    user_id, role = authenticate()
    require_role(role, ["Member", "FrontDesk"])
    booking = lookup(db.bookings, booking_id)
    facility = lookup(db.facilities, booking["facility_id"])
    member = db.members[booking["member_id"]]
    lane = db.lanes[booking["lane_id"]]

    if role == "Member" and user_id != booking["member_id"]:
        raise err(ERR_FORBIDDEN_ROLE, "Members may only confirm their own bookings")

    body = get_json_body()
    # expected_lane_version is required (PRD 2.8). Missing -> well-formedness (4).
    if body.get("expected_lane_version") is None:
        raise err(ERR_INVALID_REQUEST, "expected_lane_version is required")
    expected_lane_version = body["expected_lane_version"]
    if not isinstance(expected_lane_version, int) or isinstance(expected_lane_version, bool):
        raise err(ERR_INVALID_REQUEST, "expected_lane_version must be an integer")

    # Priority 5: state.
    if booking["status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "Booking is not in REQUESTED state")

    instructor = db.instructors.get(booking["instructor_id"]) if booking["instructor_id"] else None
    machine = db.machines.get(booking["machine_id"]) if booking["machine_id"] else None

    # Refresh waiver before reading (derived).
    recompute_member_waiver(member)

    # Priority 6: waiver.
    if not member["waiver_ok"]:
        raise err(ERR_WAIVER_REQUIRED, "Member lacks a valid waiver")

    # Priority 7: facility posture.
    _check_posture(facility, booking["kind"])

    # Priority 8: strikes.
    if member["no_show_strikes"] >= MAX_STRIKES:
        raise err(ERR_TOO_MANY_STRIKES, "Member has too many no-show strikes")

    # Priority 9: resource availability.
    _check_resource_available(booking, facility, machine)

    # OCC stale lane version — PRD 2.8: evaluated BEFORE the temporal-overlap test.
    if expected_lane_version != lane["version"]:
        raise err(ERR_STALE_LANE_VERSION, "Lane version is stale")

    # Priority 10: lane time conflict (interval + buffer overlap).
    for occ_lane in _occupied_lanes(booking):
        if booking_conflicts_on_lane(occ_lane, booking, exclude_booking_id=booking["id"]):
            raise err(ERR_LANE_TIME_CONFLICT, "Lane interval conflicts with another booking/window")

    # Priority 11: open hours.
    start = parse_iso(booking["start_utc"])
    end = parse_iso(booking["end_utc"])
    if not _interval_within_hours(facility, start, end):
        raise err(ERR_OUTSIDE_HOURS, "Booking interval outside facility open hours")

    # Priority 12: booking shape.
    _check_booking_shape(booking, instructor, member)

    # Chronological charge (peak-aware).
    final_cost = pricing.charge_cost(
        booking, lane, facility, member, instructor, machine,
        start_minute_of_day=_minute_of_day(start),
    )

    # Priority 13: funds / minutes.
    token_cost_value = 0
    if booking["pay_mode"] == "TOKEN":
        token_cost_value = pricing.token_cost(final_cost, facility["token_price_cents"])
        if member["token_balance"] < token_cost_value:
            raise err(ERR_INSUFFICIENT_FUNDS, "Insufficient token balance")
    elif booking["pay_mode"] == "MEMBERSHIP":
        projected = member["monthly_member_minutes_used"] + booking["duration_minutes"] * booking["lane_count"]
        if projected > MEMBER_MINUTE_CAP:
            raise err(ERR_INSUFFICIENT_FUNDS, "Membership minute cap exceeded")

    # Commit: write final cost + token cost, settle payment, occupy, bump lane.
    booking["final_cost_cents"] = final_cost
    booking["token_cost"] = token_cost_value
    booking["status"] = "CONFIRMED"

    if booking["pay_mode"] == "TOKEN":
        member["token_balance"] -= token_cost_value
        touch(member)
    elif booking["pay_mode"] == "MEMBERSHIP":
        member["monthly_member_minutes_used"] += booking["duration_minutes"] * booking["lane_count"]
        touch(member)

    touch(booking)
    # Lane interval occupied -> bump parent Lane version by 1 (PRD 3.5).
    touch(lane)

    return success(booking_out(booking), status=200)


def _check_posture(facility, kind):
    posture = facility["posture"]
    if posture == "CLOSED":
        raise err(ERR_FACILITY_POSTURE_BLOCK, "Facility is CLOSED")
    if posture == "RESTRICTED" and kind in ("PARTY", "TEAM_BLOCK"):
        raise err(ERR_FACILITY_POSTURE_BLOCK, "Facility RESTRICTED blocks PARTY/TEAM_BLOCK")


# ---------------------------------------------------------------------------
# Transition endpoints
# ---------------------------------------------------------------------------
@bp.post("/v1/bookings/<booking_id>/reject")
def reject_booking(booking_id):
    _, role = authenticate()
    require_role(role, ["FacilityManager"])
    booking = lookup(db.bookings, booking_id)
    if booking["status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "Booking is not REQUESTED")
    booking["status"] = "REJECTED"
    touch(booking)
    return success(booking_out(booking), status=200)


@bp.post("/v1/bookings/<booking_id>/check-in")
def check_in(booking_id):
    _, role = authenticate()
    require_role(role, ["FrontDesk"])
    booking = lookup(db.bookings, booking_id)
    if booking["status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "Booking is not CONFIRMED")

    now = clock.now()
    start = parse_iso(booking["start_utc"])
    end = parse_iso(booking["end_utc"])
    # Window: [start - EARLY_CHECKIN_MIN, end).
    if not (start - timedelta(minutes=EARLY_CHECKIN_MIN) <= now < end):
        raise err(ERR_INVALID_STATE, "Outside the check-in window")

    member = db.members.get(booking["member_id"])
    if member is not None:
        recompute_member_waiver(member)
        if not member["waiver_ok"]:
            raise err(ERR_WAIVER_REQUIRED, "Member lacks a valid waiver at check-in")

    booking["status"] = "CHECKED_IN"
    touch(booking)
    return success(booking_out(booking), status=200)


@bp.post("/v1/bookings/<booking_id>/complete")
def complete_booking(booking_id):
    _, role = authenticate()
    require_role(role, ["FrontDesk"])
    booking = lookup(db.bookings, booking_id)
    if booking["status"] != "CHECKED_IN":
        raise err(ERR_INVALID_STATE, "Booking is not CHECKED_IN")

    now = clock.now()
    start = parse_iso(booking["start_utc"])
    if now < start:
        raise err(ERR_INVALID_STATE, "Completion not permitted before start")

    booking["status"] = "COMPLETED"
    touch(booking)

    # Machine wear (PRD 3.6).
    if booking["machine_id"]:
        machine = db.machines.get(booking["machine_id"])
        if machine is not None:
            machine["pitch_count"] += PITCHES_PER_SESSION
            touch(machine)
            recompute_machine(machine)

    return success(booking_out(booking), status=200)


@bp.post("/v1/bookings/<booking_id>/cancel")
def cancel(booking_id):
    user_id, role = authenticate()
    require_role(role, ["Member", "FrontDesk"])
    booking = lookup(db.bookings, booking_id)
    if role == "Member" and user_id != booking["member_id"]:
        raise err(ERR_FORBIDDEN_ROLE, "Members may only cancel their own bookings")
    if booking["status"] not in ("REQUESTED", "CONFIRMED"):
        raise err(ERR_INVALID_STATE, "Booking cannot be cancelled from its current state")

    was_confirmed = booking["status"] == "CONFIRMED"
    cancel_booking(booking, was_confirmed=was_confirmed)
    return success(booking_out(booking), status=200)
