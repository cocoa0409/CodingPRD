"""AddonProduct and AddonBooking endpoints (PRD §3.6)."""

from flask import Blueprint, request

import db
import domain
from errors import (
    raise_err,
    ERR_ADDON_SLOT_FULL,
    ERR_BOOKING_NOT_REDEEMABLE,
    ERR_CROSS_SCOPE_REFERENCE,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SESSION_NOT_ACTIVE,
)
from helpers import (
    check_no_undeclared,
    get_body,
    ok_object,
    paginate,
    req_date,
    req_enum,
    req_int,
    req_str,
    req_time,
    require,
)

bp = Blueprint("addons", __name__)

FM = ("FarmManager",)
GATE = ("GateStaff", "FarmManager")
FIELD = ("FieldStaff", "FarmManager")
READERS = ("FarmManager", "GateStaff", "FieldStaff")
KINDS = ("WAGON_RIDE", "CAFE_VOUCHER")


# ------------------------------------------------------------- AddonProduct
@bp.post("/farm/addon-products")
def create_product():
    require(FM)
    body = get_body()
    check_no_undeclared(body, {"season_id", "kind", "name", "price_cents", "slot_capacity"})
    season_id = req_str(body, "season_id")
    kind = req_enum(body, "kind", KINDS)
    name = req_str(body, "name")
    price = req_int(body, "price_cents", min_value=0)
    slot_capacity = req_int(body, "slot_capacity", min_value=1)
    if season_id not in db.seasons:
        raise_err(ERR_NOT_FOUND, "season_id does not resolve")
    product = domain.new_entity()
    product.update(
        {
            "season_id": season_id,
            "kind": kind,
            "name": name,
            "price_cents": price,
            "slot_capacity": slot_capacity,
        }
    )
    db.addon_products[product["id"]] = product
    return ok_object(domain.serialize_addon_product(product), 201)


@bp.get("/farm/addon-products/<pid>")
def get_product(pid):
    require(READERS)
    product = db.addon_products.get(pid)
    if product is None:
        raise_err(ERR_NOT_FOUND, "AddonProduct not found")
    return ok_object(domain.serialize_addon_product(product))


@bp.get("/farm/addon-products")
def list_products():
    require(READERS)
    items = list(db.addon_products.values())
    season_id = request.args.get("season_id")
    if season_id is not None:
        items = [p for p in items if p["season_id"] == season_id]
    kind = request.args.get("kind")
    if kind is not None:
        items = [p for p in items if p["kind"] == kind]
    return paginate(items, domain.serialize_addon_product)


# ------------------------------------------------------------- AddonBooking
def slot_used(product_id, booking_date, slot_time):
    return sum(
        b["qty"]
        for b in db.addon_bookings.values()
        if b["addon_product_id"] == product_id
        and b["booking_date"] == booking_date
        and b["slot_time"] == slot_time
        and b["status"] in ("BOOKED", "REDEEMED")
    )


@bp.post("/farm/addon-bookings")
def create_booking():
    require(GATE)
    body = get_body()
    check_no_undeclared(
        body, {"session_id", "addon_product_id", "booking_date", "slot_time", "qty"}
    )
    session_id = req_str(body, "session_id")
    addon_product_id = req_str(body, "addon_product_id")
    booking_date = req_date(body, "booking_date")
    slot_time = req_time(body, "slot_time")
    qty = req_int(body, "qty", min_value=1)
    session = db.visit_sessions.get(session_id)
    if session is None:
        raise_err(ERR_NOT_FOUND, "session_id does not resolve")
    product = db.addon_products.get(addon_product_id)
    if product is None:
        raise_err(ERR_NOT_FOUND, "addon_product_id does not resolve")
    # Tier 11 (scaffold priority 93): aggregate slot capacity; equality fills.
    if slot_used(addon_product_id, booking_date, slot_time) + qty > product["slot_capacity"]:
        raise_err(ERR_ADDON_SLOT_FULL, "Add-on slot capacity exceeded")
    # Tier 12: session must be on-site.
    if session["visit_status"] not in ("CHECKED_IN", "FIELD_ACTIVE"):
        raise_err(ERR_SESSION_NOT_ACTIVE, "Session is not on-site")
    # Tier 13: cross-scope integrity.
    season = domain.season_of_session(session)
    window = domain.window_of_session(session)
    if (
        season is None
        or product["season_id"] != season["id"]
        or window is None
        or booking_date != window["date"]
    ):
        raise_err(
            ERR_CROSS_SCOPE_REFERENCE,
            "Add-on product is out of the session's season scope or booking_date mismatch",
        )
    booking = domain.new_entity()
    booking.update(
        {
            "session_id": session_id,
            "addon_product_id": addon_product_id,
            "booking_date": booking_date,
            "slot_time": slot_time,
            "qty": qty,
            "booked_value_cents": product["price_cents"] * qty,
            "status": "BOOKED",
        }
    )
    db.addon_bookings[booking["id"]] = booking
    return ok_object(domain.serialize_addon_booking(booking), 201)


@bp.get("/farm/addon-bookings/<bid>")
def get_booking(bid):
    require(READERS)
    booking = db.addon_bookings.get(bid)
    if booking is None:
        raise_err(ERR_NOT_FOUND, "AddonBooking not found")
    return ok_object(domain.serialize_addon_booking(booking))


@bp.get("/farm/addon-bookings")
def list_bookings():
    require(READERS)
    items = list(db.addon_bookings.values())
    session_id = request.args.get("session_id")
    if session_id is not None:
        items = [b for b in items if b["session_id"] == session_id]
    product_id = request.args.get("addon_product_id")
    if product_id is not None:
        items = [b for b in items if b["addon_product_id"] == product_id]
    booking_date = request.args.get("booking_date")
    if booking_date is not None:
        items = [b for b in items if b["booking_date"] == booking_date]
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return paginate(items, domain.serialize_addon_booking)


@bp.post("/farm/addon-bookings/<bid>/redeem")
def redeem_booking(bid):
    require(FIELD)
    booking = db.addon_bookings.get(bid)
    if booking is None:
        raise_err(ERR_NOT_FOUND, "AddonBooking not found")
    if booking["status"] != "BOOKED":
        raise_err(ERR_INVALID_STATE, "Only a BOOKED booking can be redeemed")
    session = db.visit_sessions.get(booking["session_id"])
    if (
        session is None
        or session["visit_status"] not in ("CHECKED_IN", "FIELD_ACTIVE")
        or db.logical_date_str() != booking["booking_date"]
    ):
        raise_err(ERR_BOOKING_NOT_REDEEMABLE, "Booking is not redeemable now")
    booking["status"] = "REDEEMED"
    domain.touch(booking)
    return ok_object(domain.serialize_addon_booking(booking))


@bp.post("/farm/addon-bookings/<bid>/release")
def release_booking_route(bid):
    require(GATE)
    booking = db.addon_bookings.get(bid)
    if booking is None:
        raise_err(ERR_NOT_FOUND, "AddonBooking not found")
    if booking["status"] != "BOOKED":
        raise_err(ERR_INVALID_STATE, "Only a BOOKED booking can be released")
    # Manual release refunds face value into the session ledger, oldest first.
    domain.release_booking(booking, refund=True)
    return ok_object(domain.serialize_addon_booking(booking))
