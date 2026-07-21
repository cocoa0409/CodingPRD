from flask import Blueprint, request

import core
from core import (
    db, ok, get_body, req_str, req_int, fetch,
    authenticate, authorize, require_owner, new_common, touch, serialize,
    sorted_by_created, paginate, reconcile_trip, credit_wallet, add_loyalty,
    parse_iso, ApiError, CHECKIN_LOYALTY_POINTS,
)

bp = Blueprint("bookings", __name__)

NON_TERMINAL_BOOKING = {"BOOKED", "WAITLISTED", "CHECKED_IN"}


def _intervals_overlap(a_start, a_end, b_start, b_end):
    # closed interval overlap (inclusive of both endpoints)
    return a_start <= b_end and b_start <= a_end


@bp.route("/coop/bookings", methods=["POST"])
def create_booking():
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    data = get_body()
    member_id = req_str(data, "member_id")
    class_trip_id = req_str(data, "class_trip_id")
    expected_version = req_int(data, "expected_classtrip_version")

    require_owner(role, uid, member_id)

    member = fetch("members", member_id)
    trip = fetch("class_trips", class_trip_id)

    # state (priority 4)
    if trip["status"] != "SCHEDULED":
        raise ApiError("ERR_TRIP_NOT_SCHEDULED", "Trip is not SCHEDULED")

    # business_safety (priority 5)
    if member["membership_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBERSHIP_INACTIVE", "Member is LAPSED; cannot book")

    # business_temporal (priority 6): member schedule conflict, closed-interval
    this_start = parse_iso(trip["start_at"])
    this_end = parse_iso(trip["end_at"])
    for b in db.bookings.values():
        if b["member_id"] != member_id:
            continue
        if b["status"] not in NON_TERMINAL_BOOKING:
            continue
        other_trip = db.class_trips.get(b["class_trip_id"])
        if other_trip is None:
            continue
        if _intervals_overlap(this_start, this_end,
                              parse_iso(other_trip["start_at"]),
                              parse_iso(other_trip["end_at"])):
            raise ApiError("ERR_MEMBER_SCHEDULE_CONFLICT",
                           "Member already has an overlapping booking")

    # business_fiscal (priority 9): need credit even for waitlist
    if member["store_credit_cents"] < trip["price_cents"]:
        raise ApiError("ERR_INSUFFICIENT_STORE_CREDIT", "Insufficient store credit to book")

    # OCC (priority 10): checked last, before side effects
    if expected_version != trip["version"]:
        raise ApiError("ERR_STALE_VERSION", "ClassTrip version has advanced")

    seated = trip["seats_available"] >= 1

    booking = new_common()
    booking.update({
        "member_id": member_id,
        "class_trip_id": class_trip_id,
        "status": "BOOKED" if seated else "WAITLISTED",
        "price_paid_cents": trip["price_cents"] if seated else 0,
        "booked_from_waitlist": False,
    })
    db.bookings[booking["id"]] = booking

    if seated:
        credit_wallet(member, -trip["price_cents"])

    reconcile_trip(trip)
    touch(trip)  # increments ClassTrip.version by 1
    return ok(serialize(booking), status=201)


@bp.route("/coop/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    booking = fetch("bookings", bid)
    require_owner(role, uid, booking["member_id"])
    return ok(serialize(booking))


@bp.route("/coop/bookings", methods=["GET"])
def list_bookings():
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    member_id = request.args.get("member_id")
    if role == "Member":
        if member_id is not None and member_id != uid:
            raise ApiError("ERR_UNAUTHORIZED", "Members may only list their own bookings")
        member_id = uid
    class_trip_id = request.args.get("class_trip_id")
    status = request.args.get("status")
    items = list(db.bookings.values())
    if member_id is not None:
        items = [b for b in items if b["member_id"] == member_id]
    if class_trip_id is not None:
        items = [b for b in items if b["class_trip_id"] == class_trip_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok(page, is_array=True, pagination=meta)


@bp.route("/coop/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    booking = fetch("bookings", bid)
    require_owner(role, uid, booking["member_id"])
    if booking["status"] not in ("BOOKED", "WAITLISTED"):
        raise ApiError("ERR_INVALID_STATE", "Booking cannot be cancelled from its current state")

    trip = fetch("class_trips", booking["class_trip_id"])
    was = booking["status"]
    booking["status"] = "CANCELLED"
    touch(booking)

    member = fetch("members", booking["member_id"])
    credit_wallet(member, booking["price_paid_cents"])  # refund (0 for waitlisted)

    if was == "BOOKED":
        # promote earliest WAITLISTED booking on the same trip
        waitlisted = [b for b in db.bookings.values()
                      if b["class_trip_id"] == trip["id"] and b["status"] == "WAITLISTED"]
        waitlisted = sorted_by_created(waitlisted)
        if waitlisted:
            promo = waitlisted[0]
            promo["status"] = "BOOKED"
            promo["booked_from_waitlist"] = True
            promo["price_paid_cents"] = trip["price_cents"]
            touch(promo)
            promo_member = fetch("members", promo["member_id"])
            credit_wallet(promo_member, -trip["price_cents"])

    reconcile_trip(trip)
    touch(trip)
    return ok(serialize(booking))


@bp.route("/coop/bookings/<bid>/check-in", methods=["POST"])
def check_in_booking(bid):
    uid, role = authenticate()
    authorize(role, {"StoreStaff"})
    booking = fetch("bookings", bid)
    if booking["status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", "Booking is not BOOKED")
    trip = fetch("class_trips", booking["class_trip_id"])
    if trip["status"] != "SCHEDULED":
        raise ApiError("ERR_TRIP_NOT_SCHEDULED", "Trip is not SCHEDULED")

    booking["status"] = "CHECKED_IN"
    touch(booking)
    member = fetch("members", booking["member_id"])
    add_loyalty(member, CHECKIN_LOYALTY_POINTS)
    return ok(serialize(booking))
