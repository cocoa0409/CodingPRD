from __future__ import annotations
from datetime import timedelta
from flask import Blueprint, request

from db import db, stamp_common, bump, parse_iso
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_FK_NOT_FOUND,
    ERR_EVENT_LEAD_TOO_SHORT,
    ERR_EVENT_CANCEL_TOO_LATE,
)
from middleware import require_roles
from pagination import parse_limit_offset, paginate
from response import created, ok, list_response
from routes._helpers import get_body, require_field, as_int, fetch, clean
from services import order as osvc
from services import calc

bp = Blueprint("events", __name__)


# ---- EventPackage ---------------------------------------------------

@bp.route("/event-packages", methods=["POST"])
@require_roles("StoreManager")
def create_event_package():
    body = get_body()
    package_code = require_field(body, "package_code")
    base_price_cents = as_int(require_field(body, "base_price_cents"), "base_price_cents")
    deposit_pct = require_field(body, "deposit_pct")
    min_lead_days = as_int(require_field(body, "min_lead_days"), "min_lead_days")

    if not isinstance(package_code, str) or not package_code:
        raise_error(ERR_INVALID_REQUEST, "package_code must be non-empty string")
    if base_price_cents < 0:
        raise_error(ERR_INVALID_REQUEST, "base_price_cents must be >= 0")
    try:
        dp = float(deposit_pct)
    except (TypeError, ValueError):
        raise_error(ERR_INVALID_REQUEST, "deposit_pct must be numeric")
        dp = 0.0
    if not (0 <= dp <= 1):
        raise_error(ERR_INVALID_REQUEST, "deposit_pct must be in [0, 1]")
    if min_lead_days < 0:
        raise_error(ERR_INVALID_REQUEST, "min_lead_days must be >= 0")
    for existing in db.event_packages.values():
        if existing["package_code"] == package_code:
            raise_error(ERR_INVALID_REQUEST, f"package_code '{package_code}' already exists")

    pkg = {
        "package_code": package_code,
        "base_price_cents": base_price_cents,
        "deposit_pct": dp,
        "min_lead_days": min_lead_days,
    }
    stamp_common(pkg)
    db.event_packages[pkg["id"]] = pkg
    return created(clean(pkg))


@bp.route("/event-packages/<id>", methods=["GET"])
@require_roles("StoreManager", "StoreClerk", "Customer")
def get_event_package(id):
    return ok(clean(fetch(db.event_packages, id)))


@bp.route("/event-packages", methods=["GET"])
@require_roles("StoreManager", "StoreClerk", "Customer")
def list_event_packages():
    limit, offset = parse_limit_offset()
    page, total = paginate(list(db.event_packages.values()), limit, offset)
    return list_response([clean(x) for x in page], limit, offset, total)


# ---- EventBooking ---------------------------------------------------

@bp.route("/event-bookings", methods=["POST"])
@require_roles("StoreClerk")
def create_event_booking():
    body = get_body()
    order_id = require_field(body, "order_id")
    event_package_id = require_field(body, "event_package_id")
    event_date = require_field(body, "event_date")

    if order_id not in db.orders:
        raise_error(ERR_FK_NOT_FOUND, f"order_id {order_id} not found")
    if event_package_id not in db.event_packages:
        raise_error(ERR_FK_NOT_FOUND, f"event_package_id {event_package_id} not found")

    order = db.orders[order_id]
    if order["fulfillment_status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "event booking attach requires DRAFT order")
    if osvc.event_booking_for(order_id) is not None:
        raise_error(ERR_INVALID_STATE, "Order already has EventBooking")

    try:
        parse_iso(event_date)
    except Exception:
        raise_error(ERR_INVALID_REQUEST, "event_date must be ISO 8601")

    pkg = db.event_packages[event_package_id]
    deposit = calc.event_deposit(int(pkg["base_price_cents"]), pkg["deposit_pct"])

    eb = {
        "order_id": order_id,
        "event_package_id": event_package_id,
        "event_date": event_date,
        "deposit_cents": deposit,
        "status": "HELD",
    }
    stamp_common(eb)
    db.event_bookings[eb["id"]] = eb
    return created(clean(eb))


@bp.route("/event-bookings/<id>", methods=["GET"])
@require_roles("StoreClerk", "Customer")
def get_event_booking(id):
    return ok(clean(fetch(db.event_bookings, id)))


@bp.route("/event-bookings", methods=["GET"])
@require_roles("StoreClerk", "Customer")
def list_event_bookings():
    limit, offset = parse_limit_offset()
    order_id = request.args.get("order_id")
    event_package_id = request.args.get("event_package_id")
    status = request.args.get("status")
    items = list(db.event_bookings.values())
    if order_id is not None:
        items = [e for e in items if e["order_id"] == order_id]
    if event_package_id is not None:
        items = [e for e in items if e["event_package_id"] == event_package_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response([clean(x) for x in page], limit, offset, total)


@bp.route("/event-bookings/<id>/confirm", methods=["POST"])
@require_roles("StoreClerk")
def confirm_booking(id):
    eb = fetch(db.event_bookings, id)
    if eb["status"] != "HELD":
        raise_error(ERR_INVALID_STATE, "confirm requires HELD")
    order = db.orders.get(eb["order_id"])
    if not order or order["payment_status"] not in {"DEPOSIT_HELD", "PAID"}:
        raise_error(ERR_INVALID_STATE, "confirm requires parent Order DEPOSIT_HELD or PAID")

    pkg = db.event_packages.get(eb["event_package_id"])
    event_dt = parse_iso(eb["event_date"])
    if pkg and (event_dt - db.clock) < timedelta(days=int(pkg["min_lead_days"])):
        raise_error(ERR_EVENT_LEAD_TOO_SHORT, "event lead too short")
    eb["status"] = "CONFIRMED"
    bump(eb)
    return ok(clean(eb))


@bp.route("/event-bookings/<id>/complete", methods=["POST"])
@require_roles("StoreClerk")
def complete_booking(id):
    eb = fetch(db.event_bookings, id)
    if eb["status"] != "CONFIRMED":
        raise_error(ERR_INVALID_STATE, "complete requires CONFIRMED")
    event_dt = parse_iso(eb["event_date"])
    if db.clock < event_dt:
        raise_error(ERR_INVALID_STATE, "complete requires clock >= event_date")

    eb["status"] = "COMPLETED"
    bump(eb)
    order = db.orders.get(eb["order_id"])
    if order and order["payment_status"] == "DEPOSIT_HELD":
        order["payment_status"] = "PAID"
        bump(order)
    return ok(clean(eb))


@bp.route("/event-bookings/<id>/cancel", methods=["POST"])
@require_roles("StoreClerk")
def cancel_booking(id):
    eb = fetch(db.event_bookings, id)
    if eb["status"] not in {"HELD", "CONFIRMED"}:
        raise_error(ERR_INVALID_STATE, "cancel requires HELD or CONFIRMED")
    event_dt = parse_iso(eb["event_date"])
    if (event_dt - db.clock) < timedelta(days=7):
        raise_error(ERR_EVENT_CANCEL_TOO_LATE, "cancel within 7 days of event")

    eb["status"] = "CANCELLED"
    bump(eb)

    order = db.orders.get(eb["order_id"])
    if order:
        cust = db.customers.get(order["customer_id"])
        if cust is not None:
            cust["store_credit_cents"] = int(cust.get("store_credit_cents", 0)) + int(
                eb["deposit_cents"]
            )
            bump(cust)
        if order["payment_status"] == "DEPOSIT_HELD":
            order["payment_status"] = "REFUNDED"
            bump(order)
    return ok(clean(eb))
