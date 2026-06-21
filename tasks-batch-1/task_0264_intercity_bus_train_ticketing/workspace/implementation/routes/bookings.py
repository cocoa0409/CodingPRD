"""Booking routes: create, read, list, confirm, pay, cancel, exchange
(PRD 3.3-3.8). Validation order follows PRD 2.11."""
from flask import Blueprint, request

import db
from errors import err
from response import success
from middleware import auth
from helpers import parse_pagination, paginate, get_json_body
from constants import FUNDING_KINDS
import serializers as ser
from services import bookings as bk

bp = Blueprint("bookings", __name__)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _ensure_owner(role, user_id, passenger_id):
    """Priority 4: a Passenger must own the resource (X-User-ID == passenger_id).
    Other roles are not subject to ownership checks (PRD 2.1)."""
    if role == "Passenger" and user_id != passenger_id:
        raise err("ERR_NOT_OWNER", "passenger does not own this resource")


# ---------------------------------------------------------------------------
# Create booking (PRD 3.3)
# ---------------------------------------------------------------------------
@bp.route("/v1/bookings", methods=["POST"])
def create_booking():
    user_id, role = auth({"Passenger"})
    body = get_json_body()

    passenger_id = body.get("passenger_id")
    if not isinstance(passenger_id, str) or not passenger_id:
        raise err("ERR_INVALID_REQUEST", "passenger_id is required")
    # Priority 3: passenger existence.
    if db.passengers.get(passenger_id) is None:
        raise err("ERR_NOT_FOUND", "passenger not found")
    # Priority 4: ownership.
    _ensure_owner(role, user_id, passenger_id)

    # Priority 5: body shape.
    funding_kind = body.get("funding_kind", "CASH")
    if funding_kind not in FUNDING_KINDS:
        raise err("ERR_INVALID_REQUEST", "funding_kind must be CASH or PASS")
    pass_id = body.get("pass_id")
    if funding_kind == "PASS":
        if not isinstance(pass_id, str) or not pass_id:
            raise err("ERR_INVALID_REQUEST", "pass_id required for PASS funding")
    else:
        if pass_id is not None:
            raise err("ERR_INVALID_REQUEST", "pass_id forbidden for CASH funding")

    legs = body.get("legs")
    if not isinstance(legs, list) or len(legs) < 1:
        raise err("ERR_INVALID_REQUEST", "legs must be a non-empty array")
    for entry in legs:
        if not isinstance(entry, dict):
            raise err("ERR_INVALID_REQUEST", "each leg must be an object")
        if not isinstance(entry.get("service_date_id"), str) or not entry.get("service_date_id"):
            raise err("ERR_INVALID_REQUEST", "leg service_date_id is required")
        if not isinstance(entry.get("fare_class_id"), str) or not entry.get("fare_class_id"):
            raise err("ERR_INVALID_REQUEST", "leg fare_class_id is required")
        if not _is_int(entry.get("leg_order")) or entry.get("leg_order") < 1:
            raise err("ERR_INVALID_REQUEST", "leg_order must be an integer >= 1")
        seat = entry.get("seat_number")
        if seat is not None and not isinstance(seat, str):
            raise err("ERR_INVALID_REQUEST", "seat_number must be a string")

    booking = bk.create_booking(passenger_id, funding_kind, pass_id, legs)
    return success(ser.booking_out(booking), 201)


@bp.route("/v1/bookings/<booking_id>", methods=["GET"])
def get_booking(booking_id):
    auth({"Passenger", "SupportAgent", "GateAgent"})
    rec = db.bookings.get(booking_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "booking not found")
    return success(ser.booking_out(rec), 200)


@bp.route("/v1/bookings", methods=["GET"])
def list_bookings():
    auth({"Passenger", "SupportAgent"})
    limit, offset = parse_pagination()
    passenger_id = request.args.get("passenger_id")
    pass_id = request.args.get("pass_id")
    recs = []
    for r in db.bookings.values():
        if passenger_id is not None and r["passenger_id"] != passenger_id:
            continue
        if pass_id is not None and r.get("pass_id") != pass_id:
            continue
        recs.append(r)
    page, meta = paginate(recs, limit, offset)
    return success([ser.booking_out(r) for r in page], 200, pagination=meta)


def _load_booking_owned(booking_id, allowed_roles):
    """Auth + existence (priority 3) + ownership (priority 4)."""
    user_id, role = auth(allowed_roles)
    rec = db.bookings.get(booking_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "booking not found")
    _ensure_owner(role, user_id, rec["passenger_id"])
    return rec, role


@bp.route("/v1/bookings/<booking_id>/confirm", methods=["POST"])
def confirm_booking(booking_id):
    rec, role = _load_booking_owned(booking_id, {"Passenger"})
    body = get_json_body()
    # Priority 5: OCC field mandatory on confirm (PRD 2.8).
    expected = body.get("expected_service_date_version")
    if not _is_int(expected):
        raise err("ERR_INVALID_REQUEST", "expected_service_date_version is required")
    booking = bk.confirm_booking(rec, expected)
    return success(ser.booking_out(booking), 200)


@bp.route("/v1/bookings/<booking_id>/pay", methods=["POST"])
def pay_booking(booking_id):
    rec, role = _load_booking_owned(booking_id, {"Passenger"})
    booking = bk.pay_booking(rec)
    return success(ser.booking_out(booking), 200)


@bp.route("/v1/bookings/<booking_id>/cancel", methods=["POST"])
def cancel_booking(booking_id):
    rec, role = _load_booking_owned(booking_id, {"Passenger", "SupportAgent"})
    body = get_json_body()
    refund_destination = body.get("refund_destination")
    booking = bk.cancel_booking(rec, refund_destination)
    return success(ser.booking_out(booking), 200)


@bp.route("/v1/bookings/<booking_id>/exchange", methods=["POST"])
def exchange_booking(booking_id):
    rec, role = _load_booking_owned(booking_id, {"Passenger", "SupportAgent"})
    body = get_json_body()

    target_sd_id = body.get("target_service_date_id")
    target_fc_id = body.get("target_fare_class_id")
    target_seat = body.get("target_seat_number")
    expected = body.get("expected_booking_version")

    # Priority 5: required fields / OCC field.
    if not isinstance(target_sd_id, str) or not target_sd_id:
        raise err("ERR_INVALID_REQUEST", "target_service_date_id is required")
    if not isinstance(target_fc_id, str) or not target_fc_id:
        raise err("ERR_INVALID_REQUEST", "target_fare_class_id is required")
    if target_seat is not None and not isinstance(target_seat, str):
        raise err("ERR_INVALID_REQUEST", "target_seat_number must be a string")
    if not _is_int(expected):
        raise err("ERR_INVALID_REQUEST", "expected_booking_version is required")

    booking = bk.exchange_booking(rec, target_sd_id, target_fc_id, target_seat, expected)
    return success(ser.booking_out(booking), 200)
