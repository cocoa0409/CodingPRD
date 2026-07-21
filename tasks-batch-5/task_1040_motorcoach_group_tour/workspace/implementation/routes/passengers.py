"""Passenger endpoints."""
from flask import Blueprint, request

import services
from errors import ApiError
from store import db
from web import (
    authenticate,
    get_body,
    created,
    ok,
    ok_list,
    parse_pagination,
    req_str,
    opt_bool,
)

bp = Blueprint("passengers", __name__)


@bp.post("/api/passengers")
def create_passenger():
    authenticate({"SalesAgent"})
    body = get_body()
    booking_id = req_str(body, "booking_id")
    full_name = req_str(body, "full_name")
    is_lead = opt_bool(body, "is_lead", False)
    roommate_passenger_id = body.get("roommate_passenger_id")
    if roommate_passenger_id is not None and not isinstance(roommate_passenger_id, str):
        raise ApiError("ERR_VALIDATION", "roommate_passenger_id must be a string")
    services.get_or_404(db.bookings, booking_id)
    if roommate_passenger_id is not None:
        services.get_or_404(db.passengers, roommate_passenger_id)
    p = services.create_passenger(booking_id, full_name, is_lead, roommate_passenger_id)
    return created(services.serialize(p))


@bp.get("/api/passengers/<passenger_id>")
def get_passenger(passenger_id):
    authenticate("ALL")
    p = services.get_or_404(db.passengers, passenger_id)
    return ok(services.serialize(p))


@bp.get("/api/passengers")
def list_passengers():
    authenticate("ALL")
    limit, offset = parse_pagination()
    args = request.args
    items = list(db.passengers.values())
    if args.get("booking_id") is not None:
        items = [p for p in items if p["booking_id"] == args.get("booking_id")]
    if args.get("roommate_passenger_id") is not None:
        items = [p for p in items if p.get("roommate_passenger_id") == args.get("roommate_passenger_id")]
    page, total = services.paginate(items, limit, offset)
    return ok_list([services.serialize(p) for p in page], total, limit, offset)
