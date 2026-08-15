"""Booking endpoints: creation, confirmation, assignment, cancellation,
completion, quote, suggestion (PRD 3.3-3.5)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
from clock import CLOCK, format_iso, parse_iso
from errors import ApiError
from middleware import ALL_ROLES, require_roles
from response import ok, ok_list
from services.core import (
    aircraft_view,
    booking_view,
    flight_leg_view,
    new_common,
    touch,
)
from util import (
    as_int,
    as_num,
    as_str,
    body,
    paginate_sorted,
    required,
    round_half_up_cents,
    to_decimal,
)

bp = Blueprint("bookings", __name__)

TIER_72H_HOURS = 72
TIER_7D_HOURS = 168


def _get_booking(bid):
    b = db.bookings.get(bid)
    if not b:
        raise ApiError("ERR_NOT_FOUND", 404, "Booking not found")
    return b


def _program_of_share(share):
    cls = db.aircraft_classes[share["class_id"]]
    return db.programs[cls["program_id"]]


def _booking_window(b):
    """(start, end) datetimes; end = departure + estimated block hours."""
    start = parse_iso(b["scheduled_departure_utc"])
    end = start + _hours_delta(b["estimated_block_hours"])
    return start, end


def _hours_delta(hours):
    from datetime import timedelta
    return timedelta(seconds=float(hours) * 3600.0)


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: [a_start, a_end) vs [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


def _aircraft_conflict(aircraft_id, exclude_booking_id, window):
    """True if the aircraft has an overlapping CONFIRMED booking window or an
    IN_PROGRESS maintenance window."""
    start, end = window
    for b in db.bookings.values():
        if b["id"] == exclude_booking_id:
            continue
        if b["assigned_aircraft_id"] != aircraft_id:
            continue
        if b["booking_status"] != "CONFIRMED":
            continue
        bs, be = _booking_window(b)
        if _overlaps(start, end, bs, be):
            return True
    for m in db.maintenance_events.values():
        if m["aircraft_id"] != aircraft_id:
            continue
        if m["event_status"] != "IN_PROGRESS":
            continue
        ms = parse_iso(m["window_start_utc"])
        me = parse_iso(m["window_end_utc"])
        if _overlaps(start, end, ms, me):
            return True
    return False


def _notice_tier(confirm_clock, departure):
    delta_hours = (departure - confirm_clock).total_seconds() / 3600.0
    if delta_hours < TIER_72H_HOURS:
        return "TIER_24H"
    if delta_hours < TIER_7D_HOURS:
        return "TIER_72H"
    return "TIER_7D"


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

@bp.route("/bookings", methods=["POST"])
def create_booking():
    user_id, role = require_roles("Owner")
    data = body()
    share_id = as_str(required(data, "share_id"), "share_id")
    requested_class_id = as_str(
        required(data, "requested_class_id"), "requested_class_id"
    )
    departure_raw = as_str(
        required(data, "scheduled_departure_utc"), "scheduled_departure_utc"
    )
    estimated = as_num(
        required(data, "estimated_block_hours"), "estimated_block_hours"
    )
    expected_version = as_int(
        required(data, "expected_share_version"), "expected_share_version"
    )

    share = db.shares.get(share_id)
    if not share:
        raise ApiError("ERR_NOT_FOUND", 404, "Share not found")
    if share["owner_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "Only the share's owner may create bookings")
    cls = db.aircraft_classes.get(requested_class_id)
    if not cls:
        raise ApiError("ERR_NOT_FOUND", 404, "Requested class not found")

    # Program posture gate (pipeline stage 5)
    program = _program_of_share(share)
    if program["program_posture"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_POSTURE_BLOCKS", 409,
                       "Program posture blocks booking creation")

    # Temporal validity (stage 7)
    try:
        departure = parse_iso(departure_raw)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "scheduled_departure_utc must be ISO 8601")
    if departure <= CLOCK.now():
        raise ApiError("ERR_TEMPORAL_INVALID", 422,
                       "scheduled_departure_utc must be strictly in the future")
    if estimated <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "estimated_block_hours must be > 0")

    # OCC (stage 12)
    if expected_version != share["version"]:
        raise ApiError("ERR_STALE_SHARE_VERSION", 412,
                       "Share version has advanced since last observation")

    rec = new_common()
    rec.update({
        "share_id": share_id,
        "requested_class_id": requested_class_id,
        "scheduled_departure_utc": format_iso(departure),
        "estimated_block_hours": round(float(estimated), 2),
        "notice_tier": None,
        "booking_status": "REQUESTED",
        "billing_status": "UNBILLED",
        "assigned_aircraft_id": None,
        "interchange_direction": "NONE",
    })
    db.bookings[rec["id"]] = rec
    touch(share)
    return ok(booking_view(rec), status=201)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

@bp.route("/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    require_roles(*ALL_ROLES)
    return ok(booking_view(_get_booking(bid)))


@bp.route("/bookings", methods=["GET"])
def list_bookings():
    require_roles(*ALL_ROLES)
    share_id = request.args.get("share_id")
    requested_class_id = request.args.get("requested_class_id")
    assigned_aircraft_id = request.args.get("assigned_aircraft_id")
    booking_status = request.args.get("booking_status")
    billing_status = request.args.get("billing_status")
    items = list(db.bookings.values())
    if share_id is not None:
        items = [b for b in items if b["share_id"] == share_id]
    if requested_class_id is not None:
        items = [b for b in items if b["requested_class_id"] == requested_class_id]
    if assigned_aircraft_id is not None:
        items = [b for b in items if b["assigned_aircraft_id"] == assigned_aircraft_id]
    if booking_status is not None:
        items = [b for b in items if b["booking_status"] == booking_status]
    if billing_status is not None:
        items = [b for b in items if b["billing_status"] == billing_status]
    page, total, limit, offset = paginate_sorted(items)
    return ok_list([booking_view(b) for b in page], total, limit, offset)


@bp.route("/flight-legs", methods=["GET"])
def list_flight_legs():
    require_roles(*ALL_ROLES)
    booking_id = request.args.get("booking_id")
    aircraft_id = request.args.get("aircraft_id")
    items = list(db.flight_legs.values())
    if booking_id is not None:
        items = [f for f in items if f["booking_id"] == booking_id]
    if aircraft_id is not None:
        items = [f for f in items if f["aircraft_id"] == aircraft_id]
    page, total, limit, offset = paginate_sorted(items)
    return ok_list([flight_leg_view(f) for f in page], total, limit, offset)


@bp.route("/flight-legs/<fid>", methods=["GET"])
def get_flight_leg(fid):
    require_roles(*ALL_ROLES)
    fl = db.flight_legs.get(fid)
    if not fl:
        raise ApiError("ERR_NOT_FOUND", 404, "Flight leg not found")
    return ok(flight_leg_view(fl))


# ---------------------------------------------------------------------------
# Quote & suggestion
# ---------------------------------------------------------------------------

@bp.route("/bookings/<bid>/quote", methods=["GET"])
def quote_booking(bid):
    require_roles(*ALL_ROLES)
    b = _get_booking(bid)
    cls = db.aircraft_classes[b["requested_class_id"]]
    hours = to_decimal(b["estimated_block_hours"])
    base = round_half_up_cents(hours * cls["hourly_rate_cents"])
    tier = b["notice_tier"]
    if tier is None:
        tier = _notice_tier(CLOCK.now(), parse_iso(b["scheduled_departure_utc"]))
    return ok({"provisional_total_cents": base, "notice_tier": tier})


@bp.route("/bookings/<bid>/suggest-aircraft", methods=["GET"])
def suggest_aircraft(bid):
    require_roles("FleetOps")
    b = _get_booking(bid)
    share = db.shares[b["share_id"]]
    program = _program_of_share(share)
    req_cls = db.aircraft_classes[b["requested_class_id"]]
    window = _booking_window(b)

    candidates = []
    for a in db.aircraft.values():
        if a["program_id"] != program["id"]:
            continue
        if a["aircraft_status"] != "IN_SERVICE":
            continue
        if _aircraft_conflict(a["id"], b["id"], window):
            continue
        candidates.append(a)
    if not candidates:
        raise ApiError("ERR_NO_AIRCRAFT_AVAILABLE", 409,
                       "No aircraft available for this booking window")

    def rank(a):
        cls = db.aircraft_classes[a["class_id"]]
        return (
            abs(cls["seats"] - req_cls["seats"]),
            a["total_hours_flown"],
            a["created_at"],
            a["id"],
        )

    candidates.sort(key=rank)
    return ok_list(
        [aircraft_view(a) for a in candidates],
        len(candidates), len(candidates), 0,
    )


# ---------------------------------------------------------------------------
# Confirm
# ---------------------------------------------------------------------------

@bp.route("/bookings/<bid>/confirm", methods=["POST"])
def confirm_booking(bid):
    user_id, role = require_roles("Owner")
    b = _get_booking(bid)
    share = db.shares[b["share_id"]]
    if share["owner_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "Only the share's owner may confirm this booking")
    # Stage 4: state
    if b["booking_status"] in ("COMPLETED", "CANCELLED", "EXPIRED"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       f"Booking is already {b['booking_status']}")
    if b["booking_status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Booking must be REQUESTED to confirm")
    if share["share_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Share must be ACTIVE to confirm")
    # Stage 5: posture
    program = _program_of_share(share)
    if program["program_posture"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_POSTURE_BLOCKS", 409,
                       "Program posture blocks confirmation")
    # Stage 6: owner standing
    owner = db.owners[share["owner_id"]]
    if owner["owner_standing"] != "GOOD":
        raise ApiError("ERR_OWNER_STANDING_BLOCKS", 422,
                       "Owner standing blocks confirmation")
    # Stage 7: temporal
    departure = parse_iso(b["scheduled_departure_utc"])
    if departure <= CLOCK.now():
        raise ApiError("ERR_TEMPORAL_INVALID", 422,
                       "scheduled_departure_utc must be strictly in the future")
    # Stage 10: entitlement gate (>= boundary permits exact equality)
    if share["hours_remaining_cy"] < b["estimated_block_hours"] - 1e-9:
        raise ApiError("ERR_ENTITLEMENT_EXHAUSTED", 422,
                       "Insufficient remaining entitlement hours")

    share["hours_remaining_cy"] = round(
        share["hours_remaining_cy"] - b["estimated_block_hours"], 2
    )
    touch(share)
    b["booking_status"] = "CONFIRMED"
    b["billing_status"] = "PROVISIONALLY_BILLED"
    b["notice_tier"] = _notice_tier(CLOCK.now(), departure)
    touch(b)
    return ok(booking_view(b))


# ---------------------------------------------------------------------------
# Assign
# ---------------------------------------------------------------------------

@bp.route("/bookings/<bid>/assign", methods=["POST"])
def assign_booking(bid):
    require_roles("FleetOps")
    b = _get_booking(bid)
    if b["booking_status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Booking must be CONFIRMED to assign")
    # Program posture: confirm/assign rejected while SUSPENDED/WINDING_DOWN/CLOSED.
    share = db.shares[b["share_id"]]
    program = _program_of_share(share)
    if program["program_posture"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_POSTURE_BLOCKS", 409,
                       "Program posture blocks assignment")
    data = body()
    aircraft_id = as_str(required(data, "aircraft_id"), "aircraft_id")
    aircraft = db.aircraft.get(aircraft_id)
    if not aircraft:
        raise ApiError("ERR_NOT_FOUND", 404, "Aircraft not found")
    if aircraft["aircraft_status"] != "IN_SERVICE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Aircraft must be IN_SERVICE to assign")
    window = _booking_window(b)
    if _aircraft_conflict(aircraft_id, b["id"], window):
        raise ApiError("ERR_AIRCRAFT_WINDOW_CONFLICT", 409,
                       "Aircraft has an overlapping booking or maintenance window")

    req_cls = db.aircraft_classes[b["requested_class_id"]]
    fly_cls = db.aircraft_classes[aircraft["class_id"]]
    if fly_cls["hourly_rate_cents"] > req_cls["hourly_rate_cents"]:
        direction = "UPGRADE"
    elif fly_cls["hourly_rate_cents"] < req_cls["hourly_rate_cents"]:
        direction = "DOWNGRADE"
    else:
        direction = "NONE"

    b["assigned_aircraft_id"] = aircraft_id
    b["interchange_direction"] = direction
    touch(b)
    return ok(booking_view(b))


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

@bp.route("/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    user_id, role = require_roles("Owner")
    b = _get_booking(bid)
    share = db.shares[b["share_id"]]
    if share["owner_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                       "Only the share's owner may cancel this booking")
    if b["booking_status"] in ("COMPLETED", "CANCELLED", "EXPIRED"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       f"Booking is already {b['booking_status']}")
    if b["booking_status"] not in ("REQUESTED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Booking must be REQUESTED or CONFIRMED to cancel")
    was_confirmed = b["booking_status"] == "CONFIRMED"
    b["booking_status"] = "CANCELLED"
    b["billing_status"] = "UNBILLED"
    touch(b)
    if was_confirmed:
        share["hours_remaining_cy"] = round(
            share["hours_remaining_cy"] + b["estimated_block_hours"], 2
        )
        touch(share)
    return ok(booking_view(b))


# ---------------------------------------------------------------------------
# Complete
# ---------------------------------------------------------------------------

@bp.route("/bookings/<bid>/complete", methods=["POST"])
def complete_booking(bid):
    require_roles("FleetOps")
    b = _get_booking(bid)
    data = body()
    actual = as_num(required(data, "actual_block_hours"), "actual_block_hours")
    if actual <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "actual_block_hours must be > 0")
    if b["booking_status"] in ("COMPLETED", "CANCELLED", "EXPIRED"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409,
                       f"Booking is already {b['booking_status']}")
    if b["booking_status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Booking must be CONFIRMED to complete")
    if not b["assigned_aircraft_id"]:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Booking has no assigned aircraft")
    share = db.shares[b["share_id"]]
    if share["share_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Share must be ACTIVE to complete (LISTED/IN_EXIT blocks)")

    actual_d = to_decimal(round(float(actual), 2))
    est_d = to_decimal(b["estimated_block_hours"])
    aircraft = db.aircraft[b["assigned_aircraft_id"]]
    program = _program_of_share(share)

    # Peak-day flag: scheduled departure UTC calendar date in the calendar.
    dep = parse_iso(b["scheduled_departure_utc"])
    peak_flag = dep.strftime("%Y-%m-%d") in program["peak_day_calendar"]

    # Create the FlightLeg.
    leg = {
        "id": db.new_id(),
        "created_at": CLOCK.now_iso(),
        "booking_id": b["id"],
        "aircraft_id": aircraft["id"],
        "actual_block_hours": float(actual_d),
        "peak_day_flag": peak_flag,
        "completed_at": CLOCK.now_iso(),
    }
    db.flight_legs[leg["id"]] = leg

    # Reconcile entitlement: += (estimated - actual); may go negative.
    delta = est_d - actual_d
    share["hours_remaining_cy"] = float(
        (to_decimal(share["hours_remaining_cy"]) + delta).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    )
    touch(share)

    aircraft["total_hours_flown"] = float(
        (to_decimal(aircraft["total_hours_flown"]) + actual_d).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    )
    touch(aircraft)

    b["booking_status"] = "COMPLETED"
    b["billing_status"] = "FINALLY_BILLED"
    touch(b)

    return ok(flight_leg_view(leg), status=201)
