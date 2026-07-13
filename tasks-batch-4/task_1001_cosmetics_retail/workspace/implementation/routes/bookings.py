"""Artists and in-store service bookings."""
from flask import Blueprint, request

from db import base_record, db, public, touch
from errors import ApiError, invalid
from middleware import (
    as_dt,
    as_enum,
    as_str,
    authenticate,
    body,
    get_artist,
    get_booking,
    get_order,
    get_customer,
    get_store,
    own_artist,
    own_customer,
    page,
    pagination,
    required,
)
from response import created, ok, ok_list
from services.booking import DURATION_MINUTES, assert_no_artist_conflict
from services.loyalty import append_ledger
from util import iso

bp = Blueprint("bookings", __name__)

ALL_ROLES = ("MerchandisingAdmin", "StoreAssociate", "BeautyArtist", "Customer")
SERVICE_TYPES = ("BROW", "MAKEOVER")
ARTIST_STATUS = ("ACTIVE", "INACTIVE")
OUTCOMES = ("COMPLETED", "NO_SHOW")
SERVICE_BONUS_POINTS = 200


def _invalid_booking_state(message):
    return ApiError("ERR_INVALID_BOOKING_STATE", message)


# --------------------------------------------------------------------------
# artists
# --------------------------------------------------------------------------

@bp.post("/artists")
def create_artist():
    authenticate("MerchandisingAdmin")
    payload = body()

    store_id = as_str(required(payload, "store_id"), "store_id")
    name = as_str(required(payload, "name"), "name")
    skills = required(payload, "skills")
    if not isinstance(skills, list) or any(s not in SERVICE_TYPES for s in skills):
        raise invalid("'skills' must be an array drawn from BROW and MAKEOVER")
    status = payload.get("status")
    status = as_enum(status, "status", ARTIST_STATUS) if status is not None else "ACTIVE"

    store = get_store(store_id)

    artist = base_record()
    artist.update({
        "store_id": store["id"],
        "name": name,
        "skills": list(skills),
        "status": status,
    })
    db.artists[artist["id"]] = artist
    return created(public(artist))


@bp.get("/artists/<artist_id>")
def read_artist(artist_id):
    authenticate(*ALL_ROLES)
    return ok(public(get_artist(artist_id)))


@bp.get("/artists")
def list_artists():
    authenticate(*ALL_ROLES)
    limit, offset = pagination()
    store_id = request.args.get("store_id")
    records = list(db.artists.values())
    if store_id:
        records = [a for a in records if a["store_id"] == store_id]
    items, total = page(records, limit, offset, public)
    return ok_list(items, limit, offset, total)


# --------------------------------------------------------------------------
# service bookings
# --------------------------------------------------------------------------

@bp.post("/service-bookings")
def create_booking():
    auth = authenticate("Customer", "StoreAssociate")
    payload = body()

    customer_id = as_str(required(payload, "customer_id"), "customer_id")
    store_id = as_str(required(payload, "store_id"), "store_id")
    artist_id = as_str(required(payload, "artist_id"), "artist_id")
    service_type = as_enum(required(payload, "service_type"), "service_type", SERVICE_TYPES)
    start_at = as_dt(required(payload, "start_at"), "start_at")
    linked_order_id = payload.get("linked_order_id")
    if linked_order_id is not None:
        linked_order_id = as_str(linked_order_id, "linked_order_id")

    customer = get_customer(customer_id)
    store = get_store(store_id)
    artist = get_artist(artist_id)
    linked_order = get_order(linked_order_id) if linked_order_id else None

    if service_type not in (artist["skills"] or []):
        raise invalid("artist %s does not hold the %s skill" % (artist["id"], service_type))
    if artist["status"] != "ACTIVE":
        raise invalid("artist %s is INACTIVE and takes no bookings" % artist["id"])

    own_customer(auth, customer["id"])

    duration = DURATION_MINUTES[service_type]
    assert_no_artist_conflict(artist["id"], start_at, duration)

    if linked_order is not None:
        if linked_order["customer_id"] != customer["id"] or linked_order["store_id"] != store["id"]:
            raise ApiError(
                "ERR_BOOKING_ORDER_MISMATCH",
                "the linked order belongs to another customer or store",
            )

    booking = base_record()
    booking.update({
        "customer_id": customer["id"],
        "store_id": store["id"],
        "artist_id": artist["id"],
        "linked_order_id": linked_order["id"] if linked_order else None,
        "service_type": service_type,
        "start_at": iso(start_at),
        "duration_minutes": duration,
        "proposed_start_at": None,
        "status": "CONFIRMED",
        "reschedule_count": 0,
        "bonus_points_awarded": 0,
    })
    db.bookings[booking["id"]] = booking
    return created(public(booking))


@bp.get("/service-bookings/<booking_id>")
def read_booking(booking_id):
    auth = authenticate(*ALL_ROLES)
    booking = get_booking(booking_id)
    own_customer(auth, booking["customer_id"])
    return ok(public(booking))


@bp.get("/service-bookings")
def list_bookings():
    auth = authenticate(*ALL_ROLES)
    limit, offset = pagination()
    customer_id = request.args.get("customer_id")
    store_id = request.args.get("store_id")
    artist_id = request.args.get("artist_id")
    linked_order_id = request.args.get("linked_order_id")

    if auth.is_customer:
        if customer_id and customer_id != auth.user_id:
            raise ApiError("ERR_FORBIDDEN_OWNERSHIP", "these bookings belong to another customer")
        customer_id = auth.user_id

    records = list(db.bookings.values())
    if customer_id:
        records = [b for b in records if b["customer_id"] == customer_id]
    if store_id:
        records = [b for b in records if b["store_id"] == store_id]
    if artist_id:
        records = [b for b in records if b["artist_id"] == artist_id]
    if linked_order_id:
        records = [b for b in records if b["linked_order_id"] == linked_order_id]
    items, total = page(records, limit, offset, public)
    return ok_list(items, limit, offset, total)


@bp.post("/service-bookings/<booking_id>/reschedule")
def reschedule_booking(booking_id):
    auth = authenticate("Customer")
    booking = get_booking(booking_id)
    payload = body()
    proposed = as_dt(required(payload, "proposed_start_at"), "proposed_start_at")

    own_customer(auth, booking["customer_id"])

    if booking["status"] != "CONFIRMED":
        raise _invalid_booking_state("only a CONFIRMED booking may be rescheduled")
    if booking["reschedule_count"] >= 2:
        raise ApiError("ERR_MAX_RESCHEDULES", "a booking may be rescheduled at most twice")

    booking["proposed_start_at"] = iso(proposed)
    booking["status"] = "RESCHEDULE_PENDING"
    touch(booking)
    return ok(public(booking))


@bp.post("/service-bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    auth = authenticate("BeautyArtist")
    booking = get_booking(booking_id)
    body()
    own_artist(auth, booking["artist_id"])

    if booking["status"] != "RESCHEDULE_PENDING":
        raise _invalid_booking_state("only a RESCHEDULE_PENDING booking may be confirmed")

    assert_no_artist_conflict(
        booking["artist_id"],
        booking["proposed_start_at"],
        booking["duration_minutes"],
        exclude_booking_id=booking["id"],
    )

    booking["start_at"] = booking["proposed_start_at"]
    booking["proposed_start_at"] = None
    booking["reschedule_count"] += 1
    booking["status"] = "CONFIRMED"
    touch(booking)
    return ok(public(booking))


@bp.post("/service-bookings/<booking_id>/complete")
def complete_booking(booking_id):
    auth = authenticate("BeautyArtist")
    booking = get_booking(booking_id)
    payload = body()
    outcome = as_enum(required(payload, "outcome"), "outcome", OUTCOMES)

    own_artist(auth, booking["artist_id"])

    if booking["status"] != "CONFIRMED":
        raise _invalid_booking_state("only a CONFIRMED booking may be closed")

    if outcome == "NO_SHOW":
        booking["status"] = "NO_SHOW"
        touch(booking)
        return ok(public(booking))

    linked_order = db.orders.get(booking["linked_order_id"]) if booking["linked_order_id"] else None
    if linked_order is not None:
        if linked_order["payment_status"] != "CAPTURED":
            raise ApiError("ERR_PAYMENT_NOT_CAPTURED", "the linked order has not been captured")

    booking["status"] = "COMPLETED"
    if linked_order is not None:
        customer = db.customers[booking["customer_id"]]
        booking["bonus_points_awarded"] = SERVICE_BONUS_POINTS
        append_ledger(customer, "SERVICE_BONUS", SERVICE_BONUS_POINTS, linked_order["id"])
        touch(customer)
    touch(booking)
    return ok(public(booking))


@bp.post("/service-bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    auth = authenticate("Customer", "StoreAssociate")
    booking = get_booking(booking_id)
    body()
    own_customer(auth, booking["customer_id"])

    if booking["status"] not in ("CONFIRMED", "RESCHEDULE_PENDING"):
        raise _invalid_booking_state("this booking is already closed")

    booking["status"] = "CANCELLED"
    touch(booking)
    return ok(public(booking))
