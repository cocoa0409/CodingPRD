"""Booking endpoints: create (OCC + full priority-ordered validation),
get, list, exchange, cancel."""

from datetime import timedelta

from flask import Blueprint, request

import store
import logic
from store import touch, parse_dt, now
from common import get_or_404, single, list_result, filter_by, as_str, exists_or_404
from auth import authenticate
from validate import (get_body, req_str, opt_str, req_enum, req_int, req_dt, opt_dt)
from errors import (ApiError, invalid_state,
                    ERR_STALE_VERSION, ERR_TRAVELER_SUSPENDED,
                    ERR_ADVANCE_PURCHASE_VIOLATION, ERR_TRAVELER_DOUBLE_BOOKED,
                    ERR_RATE_UNAVAILABLE, ERR_CREDIT_UNAVAILABLE,
                    ERR_POLICY_VIOLATION, ERR_APPROVAL_REQUIRED)

bp = Blueprint("bookings", __name__)

READERS = {"TravelManager", "Traveler", "Approver", "FinanceOfficer"}
SEGMENT_TYPES = {"AIR", "HOTEL", "CAR"}
FARE_BASES = {"REFUNDABLE", "NONREFUNDABLE"}


@bp.post("/tmc/bookings")
def create_booking():
    authenticate({"Traveler"})
    body = get_body()

    # --- Priority 3: existence, left-to-right in the input field order ---
    exists_or_404(store.trips, body.get("trip_request_id"))
    exists_or_404(store.vendors, body.get("vendor_id"))
    if body.get("negotiated_rate_id") is not None:
        exists_or_404(store.rates, body.get("negotiated_rate_id"))
    if body.get("redeem_credit_id") is not None:
        exists_or_404(store.credits, body.get("redeem_credit_id"))

    # --- Priority 4: request body well-formed ---
    trip_request_id = req_str(body, "trip_request_id")
    vendor_id = req_str(body, "vendor_id")
    rate_id = opt_str(body, "negotiated_rate_id")
    segment_type = req_enum(body, "segment_type", SEGMENT_TYPES)
    fare_basis = req_enum(body, "fare_basis", FARE_BASES)
    fare_cents = req_int(body, "fare_cents", min_value=1)
    depart_dt = req_dt(body, "depart_datetime")
    return_dt = req_dt(body, "return_datetime")
    credit_id = opt_str(body, "redeem_credit_id")
    expected_version = req_int(body, "expected_trip_request_version", min_value=0)

    trip = store.trips[trip_request_id]

    # --- Priority 6: optimistic concurrency on the trip version ---
    if expected_version != trip["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "Stale trip_request version")

    # --- Priority 8: owning traveler must be ACTIVE ---
    traveler = store.travelers.get(trip["traveler_id"])
    if not traveler or traveler["status"] != "ACTIVE":
        raise ApiError(ERR_TRAVELER_SUSPENDED, 409, "Owning traveler is not ACTIVE")
    policy = logic.policy_for_traveler(traveler)

    # --- Priority 9: advance-purchase window (whole days, >=) ---
    depart = parse_dt(depart_dt)
    if depart - now() < timedelta(days=policy["advance_purchase_days"]):
        raise ApiError(ERR_ADVANCE_PURCHASE_VIOLATION, 409, "Advance-purchase window violated")

    # --- Priority 10: per-traveler double-booking (half-open intervals) ---
    new_start = depart
    new_end = parse_dt(return_dt)
    for b in store.bookings.values():
        if b["traveler_id"] == trip["traveler_id"] and b["status"] == "TICKETED":
            es = parse_dt(b["depart_datetime"])
            ee = parse_dt(b["return_datetime"])
            if new_start < ee and es < new_end:
                raise ApiError(ERR_TRAVELER_DOUBLE_BOOKED, 409, "Overlapping TICKETED booking")

    # --- Priority 11: negotiated-rate / vendor availability ---
    if rate_id:
        rate = store.rates[rate_id]
        rate_vendor = store.vendors.get(rate["vendor_id"])
        within = parse_dt(rate["valid_from"]) <= now() <= parse_dt(rate["valid_to"])
        if rate["status"] != "ACTIVE" or not within or (rate_vendor and rate_vendor["status"] != "ACTIVE"):
            raise ApiError(ERR_RATE_UNAVAILABLE, 409, "Negotiated rate unavailable")

    # --- Priority 12: redeemed-credit eligibility ---
    credit = None
    if credit_id:
        credit = store.credits[credit_id]
        eligible = (
            credit["status"] in ("AVAILABLE", "PARTIALLY_USED")
            and now() <= parse_dt(credit["expiry_date"])
            and credit["traveler_id"] == trip["traveler_id"]
            and credit["vendor_id"] == vendor_id
        )
        if not eligible:
            raise ApiError(ERR_CREDIT_UNAVAILABLE, 409, "Credit unavailable")

    # --- Priority 13: hotel nightly-rate policy cap ---
    if segment_type == "HOTEL" and fare_cents > policy["max_hotel_nightly_cents"]:
        raise ApiError(ERR_POLICY_VIOLATION, 409, "Hotel fare exceeds policy cap")

    # --- Priority 15: trip approval gate ---
    if trip["status"] not in ("APPROVED", "BOOKED"):
        raise ApiError(ERR_APPROVAL_REQUIRED, 409, "Trip has not cleared approval")

    # --- Create the booking + run side effects ---
    booking = {
        "trip_request_id": trip_request_id,
        "traveler_id": trip["traveler_id"],
        "vendor_id": vendor_id,
        "negotiated_rate_id": rate_id,
        "segment_type": segment_type,
        "fare_basis": fare_basis,
        "fare_cents": fare_cents,
        "credit_applied_cents": 0,
        "exchange_fee_cents": 0,
        "depart_datetime": depart_dt,
        "return_datetime": return_dt,
        "status": "TICKETED",
    }
    store.stamp_new(booking)
    store.bookings[booking["id"]] = booking

    if credit is not None:
        logic.apply_credit(credit, booking)

    if trip["status"] == "APPROVED":
        trip["status"] = "BOOKED"
    logic.recompute_actual_cost(trip)
    touch(trip)  # single version bump for this create (OCC contract)

    if rate_id:
        logic.recompute_rate(store.rates[rate_id])

    return single(booking, 201)


@bp.get("/tmc/bookings/<bid>")
def get_booking(bid):
    authenticate(READERS)
    return single(get_or_404(store.bookings, bid))


@bp.get("/tmc/bookings")
def list_bookings():
    authenticate(READERS)
    recs = filter_by(store.bookings.values(), request.args,
                     {"trip_request_id": as_str, "traveler_id": as_str,
                      "vendor_id": as_str, "negotiated_rate_id": as_str,
                      "status": as_str})
    return list_result(recs)


@bp.post("/tmc/bookings/<bid>/exchange")
def exchange_booking(bid):
    authenticate({"Traveler"})
    booking = get_or_404(store.bookings, bid)
    if booking["status"] != "TICKETED":
        raise invalid_state("Booking is not TICKETED")
    trip = store.trips.get(booking["trip_request_id"])
    if not trip or trip["status"] != "BOOKED":
        raise invalid_state("Trip is not BOOKED")
    if now() > parse_dt(booking["depart_datetime"]):
        raise invalid_state("Segment cannot be exchanged after departure")

    body = get_body()
    new_fare = req_int(body, "new_fare_cents", min_value=1)
    new_vendor_id = opt_str(body, "new_vendor_id")
    new_rate_id = opt_str(body, "new_negotiated_rate_id")
    new_depart = opt_dt(body, "new_depart_datetime")
    new_return = opt_dt(body, "new_return_datetime")
    if new_vendor_id is not None:
        exists_or_404(store.vendors, new_vendor_id)
    if new_rate_id is not None:
        exists_or_404(store.rates, new_rate_id)

    traveler = store.travelers.get(trip["traveler_id"])
    policy = logic.policy_for_traveler(traveler)
    penalty = policy["exchange_penalty_cents"]
    old_fare = booking["fare_cents"]

    booking["status"] = "EXCHANGED"
    touch(booking)

    new_booking = {
        "trip_request_id": booking["trip_request_id"],
        "traveler_id": booking["traveler_id"],
        "vendor_id": new_vendor_id or booking["vendor_id"],
        "negotiated_rate_id": new_rate_id if new_rate_id is not None else booking.get("negotiated_rate_id"),
        "segment_type": booking["segment_type"],
        "fare_basis": booking["fare_basis"],
        "fare_cents": new_fare,
        "credit_applied_cents": 0,
        "exchange_fee_cents": penalty,
        "depart_datetime": new_depart or booking["depart_datetime"],
        "return_datetime": new_return or booking["return_datetime"],
        "status": "TICKETED",
    }
    store.stamp_new(new_booking)
    store.bookings[new_booking["id"]] = new_booking

    residual = max(0, old_fare - new_fare - penalty)
    if residual > 0:
        logic.issue_credit(booking["traveler_id"], booking["id"],
                           booking["vendor_id"], residual, policy)

    old_rate_id = booking.get("negotiated_rate_id")
    if old_rate_id:
        logic.recompute_rate(store.rates.get(old_rate_id))
    if new_booking["negotiated_rate_id"]:
        logic.recompute_rate(store.rates.get(new_booking["negotiated_rate_id"]))

    logic.recompute_actual_cost(trip)
    touch(trip)

    return single(new_booking, 201)


@bp.post("/tmc/bookings/<bid>/cancel")
def cancel_booking(bid):
    authenticate({"Traveler"})
    booking = get_or_404(store.bookings, bid)
    if booking["status"] != "TICKETED":
        raise invalid_state("Booking is not TICKETED")
    logic.terminate_booking(booking)
    trip = store.trips.get(booking["trip_request_id"])
    if trip:
        logic.recompute_actual_cost(trip)
        touch(trip)
    return single(booking)
