"""Ride passes, bookings, dispatch, decline and confirmation — PRD 3.5, 3.6."""

from flask import Blueprint

import calc
import serialize
import validation as v
from auth import require
from envelope import (created, ok, ok_list, read_pagination, paginate,
                      enum_param, str_param)
from errors import ApiError
from store import store, parse_date

bp = Blueprint("bookings", __name__)

BOOKING_STATUSES = ("REQUESTED", "OFFERED", "CONFIRMED", "BOARDED",
                    "COMPLETED", "INTERRUPTED", "UNFULFILLED")


def find_pass(pass_id):
    row = store.ride_passes.get(pass_id)
    if row is None:
        raise ApiError("ERR_RIDE_PASS_NOT_FOUND", "No ride pass with id %s." % pass_id)
    return row


def find_booking(booking_id):
    row = store.bookings.get(booking_id)
    if row is None:
        raise ApiError("ERR_BOOKING_NOT_FOUND", "No booking with id %s." % booking_id)
    return row


def _require_owner(actor, owner_user_id):
    if actor.user_id != owner_user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "The acting user does not own this resource.")


# ------------------------------------------------------------ ride passes

@bp.post("/harbor/ride-passes")
def create_ride_pass():
    actor = require("Rider")
    body = v.body()
    zone_tier = v.get_enum(body, "zone_tier", ("INNER", "OUTER", "ALL_ZONE"))
    rides_purchased = v.get_integer(body, "rides_purchased", minimum=1)
    purchase_price = v.get_integer(body, "purchase_price_cents", minimum=0)
    valid_until_raw, _valid_until = v.get_calendar_date(body, "valid_until")

    row = store.new_row()
    row.update({
        "rider_user_id": actor.user_id,
        "zone_tier": zone_tier,
        "rides_purchased": rides_purchased,
        "purchase_price_cents": purchase_price,
        "valid_until": valid_until_raw,
        "rides_remaining": rides_purchased,
        "status": "ACTIVE",
        "refund_basis": None,
        "refund_amount_cents": 0,
    })
    store.ride_passes[row["id"]] = row
    return created(serialize.ride_pass(row))


@bp.get("/harbor/ride-passes/<pass_id>")
def read_ride_pass(pass_id):
    require("Rider", "HarborAdmin", "Dispatcher", "FareAuditor")
    return ok(serialize.ride_pass(find_pass(pass_id)))


@bp.post("/harbor/ride-passes/<pass_id>/refund")
def refund_ride_pass(pass_id):
    actor = require("Rider")
    ride_pass = find_pass(pass_id)
    _require_owner(actor, ride_pass["rider_user_id"])
    body = v.body()
    settlement_basis = v.get_enum(body, "settlement_basis", ("PRO_RATA", "DIFFERENTIAL"))

    # rung 10 — state precondition
    if ride_pass["status"] not in ("ACTIVE", "EXHAUSTED"):
        raise ApiError("ERR_PASS_NOT_ACTIVE", "The pass may no longer be refunded.")

    amount = calc.ride_pass_residual_value(ride_pass, settlement_basis)
    ride_pass["refund_basis"] = settlement_basis
    ride_pass["refund_amount_cents"] = amount
    ride_pass["rides_remaining"] = 0
    ride_pass["status"] = "REFUNDED"
    store.touch(ride_pass)
    return ok(serialize.ride_pass(ride_pass))


# --------------------------------------------------------------- bookings

@bp.post("/harbor/bookings")
def create_booking():
    actor = require("Rider")
    body = v.body()

    # rung 4 — body foreign keys, in the endpoint's declared field order
    origin = _resolve(body, "origin_stop_id", store.stops, "ERR_STOP_NOT_FOUND")
    destination = _resolve(body, "destination_stop_id", store.stops, "ERR_STOP_NOT_FOUND")

    day = None
    requested_raw = body.get("requested_date")
    if isinstance(requested_raw, str) and parse_date(requested_raw) is not None:
        day = calc.day_by_date(requested_raw)
        if day is None:
            raise ApiError("ERR_SERVICE_DAY_NOT_FOUND",
                           "No operating day has been opened for %s." % requested_raw)

    ride_pass = None
    if body.get("ride_pass_id") is not None:
        ride_pass = _resolve(body, "ride_pass_id", store.ride_passes,
                             "ERR_RIDE_PASS_NOT_FOUND")

    # rung 6 — payload validity
    v.get_string(body, "origin_stop_id", min_len=1)
    v.get_string(body, "destination_stop_id", min_len=1)
    requested_date_raw, _requested_date = v.get_calendar_date(body, "requested_date")
    service_mode = v.get_enum(body, "service_mode", ("SCHEDULED", "ON_DEMAND"))
    party_size = v.get_integer(body, "party_size", minimum=1, maximum=12)
    v.get_string(body, "ride_pass_id", required=False, default=None, nullable=True, min_len=1)

    # rung 8 — distinct endpoints
    if origin["id"] == destination["id"]:
        raise ApiError("ERR_SAME_ORIGIN_DESTINATION",
                       "origin_stop_id and destination_stop_id must differ.")

    fare = calc.booking_fare_quote(origin, destination, day, service_mode, party_size)

    row = store.new_row()
    row.update({
        "rider_user_id": actor.user_id,
        "trip_id": None,
        "ride_pass_id": ride_pass["id"] if ride_pass is not None else None,
        "origin_stop_id": origin["id"],
        "destination_stop_id": destination["id"],
        "requested_date": requested_date_raw,
        "service_mode": service_mode,
        "party_size": party_size,
        "offer_round": 0,
        "declined_trip_ids": [],
        "status": "REQUESTED",
        "redemption_status": "NONE",
        "interrupted_from_status": None,
        "fare_quoted_cents": fare,
        "fare_charged_cents": 0,
        "fare_refunded_cents": 0,
        "credit_refunded_cents": 0,
    })
    store.bookings[row["id"]] = row
    return created(serialize.booking(row))


def _resolve(body, key, table, error_id):
    candidate = v.fk_candidate(body, key)
    if candidate is None:
        return None
    row = table.get(candidate)
    if row is None:
        raise ApiError(error_id, "No resource with id %s." % candidate)
    return row


@bp.get("/harbor/bookings/<booking_id>")
def read_booking(booking_id):
    require("Rider", "Dispatcher", "HarborAdmin", "VesselMaster", "FareAuditor")
    return ok(serialize.booking(find_booking(booking_id)))


@bp.get("/harbor/bookings")
def list_bookings():
    require("Rider", "Dispatcher", "HarborAdmin", "VesselMaster", "FareAuditor")
    limit, offset = read_pagination()
    trip_id = str_param("trip_id")
    ride_pass_id = str_param("ride_pass_id")
    origin_stop_id = str_param("origin_stop_id")
    destination_stop_id = str_param("destination_stop_id")
    rider_user_id = str_param("rider_user_id")
    status = enum_param("status", BOOKING_STATUSES)

    rows = []
    for booking in store.bookings.values():
        if trip_id is not None and booking["trip_id"] != trip_id:
            continue
        if ride_pass_id is not None and booking["ride_pass_id"] != ride_pass_id:
            continue
        if origin_stop_id is not None and booking["origin_stop_id"] != origin_stop_id:
            continue
        if destination_stop_id is not None and booking["destination_stop_id"] != destination_stop_id:
            continue
        if rider_user_id is not None and booking["rider_user_id"] != rider_user_id:
            continue
        if status is not None and booking["status"] != status:
            continue
        rows.append(booking)
    rows = store.ordered(rows)
    window = paginate(rows, limit, offset)
    return ok_list([serialize.booking(r) for r in window], limit, offset, len(rows))


@bp.post("/harbor/bookings/<booking_id>/dispatch")
def dispatch_booking(booking_id):
    require("Dispatcher")
    booking = find_booking(booking_id)

    # rung 10 — state precondition
    if booking["status"] != "REQUESTED":
        raise ApiError("ERR_BOOKING_NOT_REQUESTED", "The booking is not REQUESTED.")

    # rung 24 — dispatch pool
    candidates = calc.dispatch_candidates(booking)
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_TRIP", "No eligible trip is available.")

    booking["trip_id"] = candidates[0]["id"]
    booking["status"] = "OFFERED"
    store.touch(booking)
    return ok(serialize.booking(booking))


@bp.post("/harbor/bookings/<booking_id>/decline")
def decline_booking(booking_id):
    actor = require("Rider")
    booking = find_booking(booking_id)
    _require_owner(actor, booking["rider_user_id"])

    # rung 10 — state precondition
    if booking["status"] != "OFFERED":
        raise ApiError("ERR_BOOKING_NOT_OFFERED", "The booking is not OFFERED.")

    if booking["trip_id"] is not None:
        booking["declined_trip_ids"] = list(booking["declined_trip_ids"]) + [booking["trip_id"]]
    booking["trip_id"] = None
    booking["offer_round"] = booking["offer_round"] + 1
    if booking["offer_round"] >= calc.MAX_OFFER_ROUNDS:
        booking["status"] = "UNFULFILLED"
    else:
        booking["status"] = "REQUESTED"
    store.touch(booking)
    return ok(serialize.booking(booking))


@bp.post("/harbor/bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    actor = require("Rider")
    booking = find_booking(booking_id)
    _require_owner(actor, booking["rider_user_id"])
    body = v.body()

    # rung 6 — payload validity
    expected_trip_version = v.get_integer(body, "expected_trip_version")

    # rung 10 — state preconditions
    if booking["status"] != "OFFERED":
        raise ApiError("ERR_BOOKING_NOT_OFFERED", "The booking is not OFFERED.")
    trip = store.trips.get(booking["trip_id"])
    if trip is None:
        raise ApiError("ERR_TRIP_NOT_FOUND", "The offered trip no longer exists.")
    if trip["operational_status"] != "SCHEDULED":
        raise ApiError("ERR_TRIP_NOT_SCHEDULED", "The offered trip is not SCHEDULED.")

    # rung 11 — optimistic concurrency on the trip
    if expected_trip_version != trip["version"]:
        raise ApiError("ERR_STALE_TRIP_VERSION",
                       "expected_trip_version does not match the trip's current version.")

    # rung 12 — suspended service
    day = store.service_days.get(trip["service_day_id"])
    if day is not None and day["posture"] == "SUSPENDED":
        raise ApiError("ERR_SERVICE_SUSPENDED", "The operating day is SUSPENDED.")

    ride_pass = store.ride_passes.get(booking["ride_pass_id"]) if booking["ride_pass_id"] else None

    if ride_pass is not None:
        # rung 20 — pass validity date (a stale pass is moved to EXPIRED first)
        valid_until = parse_date(ride_pass["valid_until"])
        if valid_until is None or valid_until < store.clock_date():
            if ride_pass["status"] == "ACTIVE":
                ride_pass["status"] = "EXPIRED"
                store.touch(ride_pass)
            raise ApiError("ERR_PASS_EXPIRED", "The tendered pass has expired.")

        # rung 22 — pass zone coverage
        origin = store.stops.get(booking["origin_stop_id"])
        destination = store.stops.get(booking["destination_stop_id"])
        span = calc.zone_span(origin, destination)
        if not calc.pass_covers_span(ride_pass["zone_tier"], span):
            raise ApiError("ERR_PASS_ZONE_NOT_COVERED",
                           "The pass tier does not cover this zone span.")

        # pass state
        if ride_pass["status"] != "ACTIVE":
            raise ApiError("ERR_PASS_NOT_ACTIVE", "The tendered pass is not ACTIVE.")

    # rung 25 — seat capacity
    remaining = calc.trip_effective_capacity(trip) - trip["seats_committed"]
    if remaining < booking["party_size"]:
        raise ApiError("ERR_TRIP_CAPACITY_EXCEEDED",
                       "The party does not fit in the trip's remaining capacity.")

    # rung 26 — ride balance
    if ride_pass is not None and ride_pass["rides_remaining"] < booking["party_size"]:
        raise ApiError("ERR_PASS_NO_RIDES_REMAINING",
                       "The pass has too few rides remaining.")

    if ride_pass is not None:
        ride_pass["rides_remaining"] = ride_pass["rides_remaining"] - booking["party_size"]
        booking["redemption_status"] = "REDEEMED"
        booking["fare_charged_cents"] = 0
        if ride_pass["rides_remaining"] == 0:
            ride_pass["status"] = "EXHAUSTED"
        store.touch(ride_pass)
    else:
        booking["fare_charged_cents"] = booking["fare_quoted_cents"]

    booking["status"] = "CONFIRMED"
    store.touch(booking)
    calc.recompute_seats_committed(trip)
    store.touch(trip)
    return ok(serialize.booking(booking))
