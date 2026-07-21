from flask import Blueprint

import core
from core import (
    db, ok, get_body, req_str, req_int, req_enum, req_datetime, fetch,
    authenticate, authorize, new_common, touch, serialize,
    reconcile_trip, credit_wallet, add_loyalty, ApiError, CHECKIN_LOYALTY_POINTS,
)

bp = Blueprint("classtrips", __name__)

TRIP_CATEGORIES = {"CLASS", "GUIDED_TRIP"}


@bp.route("/coop/class-trips", methods=["POST"])
def create_class_trip():
    uid, role = authenticate()
    authorize(role, {"StoreStaff"})
    data = get_body()
    title = req_str(data, "title")
    category = req_enum(data, "category", TRIP_CATEGORIES)
    start_at = req_datetime(data, "start_at")
    end_at = req_datetime(data, "end_at")
    capacity = req_int(data, "capacity", min_value=1)
    price_cents = req_int(data, "price_cents", min_value=0)

    trip = new_common()
    trip.update({
        "title": title,
        "category": category,
        "start_at": start_at,
        "end_at": end_at,
        "capacity": capacity,
        "price_cents": price_cents,
        "status": "SCHEDULED",
        "seats_reserved": 0,
        "seats_available": capacity,
        "waitlist_count": 0,
    })
    db.class_trips[trip["id"]] = trip
    return ok(serialize(trip), status=201)


@bp.route("/coop/class-trips/<cid>", methods=["GET"])
def get_class_trip(cid):
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    trip = fetch("class_trips", cid)
    return ok(serialize(trip))


@bp.route("/coop/class-trips/<cid>/cancel", methods=["POST"])
def cancel_class_trip(cid):
    uid, role = authenticate()
    authorize(role, {"StoreStaff"})
    trip = fetch("class_trips", cid)
    if trip["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Trip is not SCHEDULED")

    for b in db.bookings.values():
        if b["class_trip_id"] != cid:
            continue
        if b["status"] in ("BOOKED", "WAITLISTED", "CHECKED_IN"):
            was = b["status"]
            b["status"] = "CANCELLED"
            touch(b)
            member = fetch("members", b["member_id"])
            credit_wallet(member, b["price_paid_cents"])  # refund (0 for waitlisted)
            if was == "CHECKED_IN":
                add_loyalty(member, -CHECKIN_LOYALTY_POINTS)

    trip["status"] = "CANCELLED"
    reconcile_trip(trip)
    touch(trip)
    return ok(serialize(trip))


@bp.route("/coop/class-trips/<cid>/complete", methods=["POST"])
def complete_class_trip(cid):
    uid, role = authenticate()
    authorize(role, {"StoreStaff"})
    trip = fetch("class_trips", cid)
    if trip["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Trip is not SCHEDULED")

    for b in db.bookings.values():
        if b["class_trip_id"] != cid:
            continue
        if b["status"] == "BOOKED":
            b["status"] = "NO_SHOW"  # no refund
            touch(b)

    trip["status"] = "COMPLETED"
    reconcile_trip(trip)
    touch(trip)
    return ok(serialize(trip))
