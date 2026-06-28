"""PreSaleOrder routes: create, get, list, pay, cancel."""
from flask import Blueprint, request

from clock import clock, parse_iso, format_iso_millis
from db import db, stamp_create, touch, sorted_by_created
from middleware import authenticate, authorize
from validators import (
    get_json_body, require, as_str, as_int, as_bool, parse_pagination, invalid,
)
from lookups import get_order_path, get_ref
from response import success_object, success_array
import serializers as ser
from services.calculations import presale_price
from services.derive import recompute_yearbook
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_PRESALE_NOT_OPEN, ERR_ALREADY_DISTRIBUTED,
)

bp = Blueprint("presale_orders", __name__)


@bp.route("/yearbooks/presale-orders", methods=["POST"])
def create_order():
    _, role = authenticate()
    authorize(role, {"SalesRep"})
    body = get_json_body()

    yearbook_id = as_str(require(body, "yearbook_id"), "yearbook_id")
    yb = get_ref(db.yearbooks, yearbook_id)
    buyer_name = as_str(require(body, "buyer_name"), "buyer_name")
    quantity = as_int(require(body, "quantity"), "quantity")
    if quantity < 1:
        invalid("quantity must be >= 1")

    personalize = body.get("personalize", False)
    if personalize is None:
        personalize = False
    personalize = as_bool(personalize, "personalize")

    stamp_name = body.get("stamp_name", "")
    if stamp_name is None:
        stamp_name = ""
    stamp_name = as_str(stamp_name, "stamp_name")
    if personalize and stamp_name == "":
        invalid("stamp_name must be non-empty when personalize is true")

    # order time from logical clock; determine tier vs the pre-sale window
    ordered_at = clock.now()
    open_iso = parse_iso(yb["presale_open_iso"])
    close_iso = parse_iso(yb["presale_close_iso"])

    if ordered_at < open_iso:
        raise ApiError(ERR_PRESALE_NOT_OPEN, 409, "pre-sale window has not opened")
    price_tier = "EARLY" if ordered_at < close_iso else "STANDARD"

    total_price_cents = presale_price(price_tier, personalize, quantity)

    order = {
        "yearbook_id": yearbook_id,
        "buyer_name": buyer_name,
        "quantity": quantity,
        "personalize": personalize,
        "stamp_name": stamp_name,
        "ordered_at_iso": format_iso_millis(ordered_at),
        "price_tier": price_tier,
        "total_price_cents": total_price_cents,
        "status": "PLACED",
    }
    stamp_create(order)
    db.presale_orders[order["id"]] = order
    return success_object(ser.presale_order(order), 201)


@bp.route("/yearbooks/presale-orders/<order_id>", methods=["GET"])
def get_order(order_id):
    _, role = authenticate()
    authorize(role, {"Adviser", "SalesRep"})
    order = get_order_path(order_id)
    return success_object(ser.presale_order(order), 200)


@bp.route("/yearbooks/presale-orders", methods=["GET"])
def list_orders():
    _, role = authenticate()
    authorize(role, {"Adviser", "SalesRep"})
    limit, offset = parse_pagination()
    yearbook_id = request.args.get("yearbook_id")
    records = list(db.presale_orders.values())
    if yearbook_id is not None:
        records = [r for r in records if r["yearbook_id"] == yearbook_id]
    records = sorted_by_created(records)
    total = len(records)
    page = records[offset:offset + limit]
    return success_array([ser.presale_order(r) for r in page], limit, offset, total, 200)


@bp.route("/yearbooks/presale-orders/<order_id>/pay", methods=["POST"])
def pay_order(order_id):
    _, role = authenticate()
    authorize(role, {"SalesRep"})
    order = get_order_path(order_id)
    if order["status"] != "PLACED":
        raise ApiError(ERR_INVALID_STATE, 409, "order is not PLACED")
    order["status"] = "PAID"
    touch(order)
    yb = db.yearbooks.get(order["yearbook_id"])
    if yb is not None:
        recompute_yearbook(yb)
    return success_object(ser.presale_order(order), 200)


@bp.route("/yearbooks/presale-orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    _, role = authenticate()
    authorize(role, {"SalesRep"})
    order = get_order_path(order_id)
    if order["status"] not in ("PLACED", "PAID"):
        raise ApiError(ERR_INVALID_STATE, 409, "order cannot be cancelled")

    was_paid = order["status"] == "PAID"
    if was_paid:
        # blocked once any print run reached SHIPPED/DELIVERED
        yb_id = order["yearbook_id"]
        distributed = any(
            r["yearbook_id"] == yb_id and r["status"] in ("SHIPPED", "DELIVERED")
            for r in db.print_runs.values()
        )
        if distributed:
            raise ApiError(ERR_ALREADY_DISTRIBUTED, 409,
                           "a print run has already shipped/delivered")

    order["status"] = "CANCELLED"
    touch(order)
    if was_paid:
        yb = db.yearbooks.get(order["yearbook_id"])
        if yb is not None:
            recompute_yearbook(yb)
    return success_object(ser.presale_order(order), 200)
