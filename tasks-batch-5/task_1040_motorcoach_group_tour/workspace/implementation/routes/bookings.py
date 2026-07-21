"""Booking endpoints."""
from flask import Blueprint, request

import services
from store import db
from web import (
    authenticate,
    get_body,
    created,
    ok,
    ok_list,
    parse_pagination,
    req_str,
    req_int,
    opt_bool,
    opt_str,
)

bp = Blueprint("bookings", __name__)


@bp.post("/api/bookings")
def create_booking():
    authenticate({"SalesAgent"})
    body = get_body()
    departure_id = req_str(body, "departure_id")
    lead_name = req_str(body, "lead_name")
    pax_count = req_int(body, "pax_count", min_val=1)
    rooms_requested = req_int(body, "rooms_requested", min_val=0)
    insurance_opt_in = opt_bool(body, "insurance_opt_in", False)
    services.get_or_404(db.departures, departure_id)
    booking = services.create_booking(
        departure_id, lead_name, pax_count, rooms_requested, insurance_opt_in
    )
    return created(services.serialize(booking))


@bp.get("/api/bookings/<booking_id>")
def get_booking(booking_id):
    authenticate("ALL")
    b = services.get_or_404(db.bookings, booking_id)
    return ok(services.serialize(b))


@bp.get("/api/bookings")
def list_bookings():
    authenticate("ALL")
    limit, offset = parse_pagination()
    args = request.args
    items = list(db.bookings.values())
    if args.get("departure_id") is not None:
        items = [b for b in items if b["departure_id"] == args.get("departure_id")]
    if args.get("reservation_status") is not None:
        items = [b for b in items if b["reservation_status"] == args.get("reservation_status")]
    page, total = services.paginate(items, limit, offset)
    return ok_list([services.serialize(b) for b in page], total, limit, offset)


@bp.post("/api/bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    authenticate({"SalesAgent"})
    b = services.get_or_404(db.bookings, booking_id)
    services.confirm_booking(b)
    return ok(services.serialize(b))


@bp.post("/api/bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    authenticate({"SalesAgent"})
    b = services.get_or_404(db.bookings, booking_id)
    body = get_body()
    reason = opt_str(body, "reason")
    services.cancel_booking(b, reason)
    return ok(services.serialize(b))
