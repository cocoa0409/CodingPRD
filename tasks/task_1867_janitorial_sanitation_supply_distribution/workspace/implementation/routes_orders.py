"""Order and order line endpoints."""
from flask import Blueprint, request

import clock
import db
import services as svc
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_FACILITY_INACTIVE, ERR_VALIDATION,
    not_found,
)
from middleware import require_roles, check_facility_ownership
from response import success_object, success_list
from routes_facilities import get_facility_or_404

bp = Blueprint("orders", __name__)

READ_ROLES = ("DistributorAdmin", "FacilityManager", "SalesRep")
WRITE_ROLES = ("FacilityManager", "DistributorAdmin")


def _pagination():
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise ApiError(ERR_VALIDATION, "limit/offset must be integers", 400)
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError(ERR_VALIDATION, "limit must be 1..100, offset >= 0", 400)
    return limit, offset


def validate_lines(lines_raw):
    if not isinstance(lines_raw, list) or len(lines_raw) == 0:
        raise ApiError(ERR_VALIDATION, "lines must be a non-empty array", 400)
    lines = []
    for i, entry in enumerate(lines_raw):
        if not isinstance(entry, dict):
            raise ApiError(ERR_VALIDATION, "lines[%d] must be an object" % i, 400)
        pid = svc.as_str(svc.require_field(entry, "product_id"), "lines[%d].product_id" % i)
        qty = svc.as_int(svc.require_field(entry, "qty"), "lines[%d].qty" % i, minimum=1)
        discount = entry.get("discount_pct", 0)
        discount = svc.as_number(discount, "lines[%d].discount_pct" % i)
        if discount < 0 or discount > 1:
            raise ApiError(ERR_VALIDATION, "discount_pct must be in 0..1", 400)
        if pid not in db.products:
            raise not_found("Product not found: %s" % pid)
        lines.append({"product_id": pid, "qty": qty, "discount_pct": discount})
    return lines


def create_order_record(facility_id, lines, delivery_date, fuel_index,
                        source="MANUAL", standing_order_id=None):
    o = svc.base_resource()
    o.update({
        "facility_id": facility_id,
        "standing_order_id": standing_order_id,
        "source": source,
        "delivery_date": clock.iso_format(delivery_date),
        "fuel_index": fuel_index,
        "fuel_index_at_delivery": None,
        "merchandise_subtotal_cents": 0,
        "delivery_fee_cents": 0,
        "fuel_surcharge_cents": 0,
        "fuel_surcharge_variant": "QUOTED",
        "trial_credit_cents": 0,
        "total_cents": 0,
        "status": "DRAFT",
        "placed_at": None,
    })
    db.orders[o["id"]] = o
    for line in lines:
        ol = svc.base_resource()
        ol.update({
            "order_id": o["id"],
            "product_id": line["product_id"],
            "qty": line["qty"],
            "discount_pct": line["discount_pct"],
            "unit_price_cents": 0,
            "line_total_cents": 0,
            "status": "PENDING",
        })
        db.order_lines[ol["id"]] = ol
    return o


@bp.post("/jansan/orders")
def create_order():
    user_id, role = require_roles(*WRITE_ROLES)
    body = request.get_json(silent=True) or {}
    facility_id = svc.as_str(svc.require_field(body, "facility_id"), "facility_id")
    check_facility_ownership(user_id, role, facility_id)
    get_facility_or_404(facility_id)
    lines = validate_lines(svc.require_field(body, "lines"))
    delivery_date = svc.as_datetime(svc.require_field(body, "delivery_date"), "delivery_date")
    fuel_index = svc.as_number(svc.require_field(body, "fuel_index"), "fuel_index")
    o = create_order_record(facility_id, lines, delivery_date, fuel_index)
    return success_object(dict(o), 201)


def get_order_or_404(order_id):
    o = db.orders.get(order_id)
    if o is None:
        raise not_found("Order not found")
    return o


@bp.get("/jansan/orders/<order_id>")
def get_order(order_id):
    user_id, role = require_roles(*READ_ROLES)
    o = get_order_or_404(order_id)
    check_facility_ownership(user_id, role, o["facility_id"])
    return success_object(dict(o))


@bp.get("/jansan/orders")
def list_orders():
    user_id, role = require_roles(*READ_ROLES)
    facility_id = request.args.get("facility_id")
    standing_order_id = request.args.get("standing_order_id")
    status = request.args.get("status")
    limit, offset = _pagination()
    items = list(db.orders.values())
    if role == "FacilityManager":
        items = [o for o in items if o["facility_id"] == user_id]
    if facility_id:
        items = [o for o in items if o["facility_id"] == facility_id]
    if standing_order_id:
        items = [o for o in items if o["standing_order_id"] == standing_order_id]
    if status:
        items = [o for o in items if o["status"] == status]
    items.sort(key=lambda o: clock.parse_iso(o["created_at"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([dict(o) for o in page], limit, offset, total)


@bp.post("/jansan/orders/<order_id>/place")
def place_order_endpoint(order_id):
    user_id, role = require_roles(*WRITE_ROLES)
    o = get_order_or_404(order_id)
    check_facility_ownership(user_id, role, o["facility_id"])
    if o["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Order is not DRAFT", 409)
    facility = db.facilities.get(o["facility_id"])
    if facility is None or facility["status"] != "ACTIVE":
        raise ApiError(ERR_FACILITY_INACTIVE, "Facility is not ACTIVE", 409)
    svc.place_order(o)
    return success_object(dict(o))


@bp.post("/jansan/orders/<order_id>/confirm-delivery")
def confirm_delivery(order_id):
    require_roles("DistributorAdmin")
    o = get_order_or_404(order_id)
    if o["status"] != "PLACED":
        raise ApiError(ERR_INVALID_STATE, "Order is not PLACED", 409)
    body = request.get_json(silent=True) or {}
    fiad = svc.as_number(svc.require_field(body, "fuel_index_at_delivery"), "fuel_index_at_delivery")
    o["fuel_index_at_delivery"] = fiad
    # ACTUAL surcharge recompute on the same combined base
    base = o["merchandise_subtotal_cents"] + o["delivery_fee_cents"]
    facility = db.facilities.get(o["facility_id"])
    miles = facility["delivery_distance_miles"] if facility else 0
    o["fuel_surcharge_cents"] = svc.compute_fuel_surcharge(base, fiad, miles)
    o["fuel_surcharge_variant"] = "ACTUAL"
    total = (o["merchandise_subtotal_cents"] + o["delivery_fee_cents"]
             + o["fuel_surcharge_cents"] - o["trial_credit_cents"])
    o["total_cents"] = max(0, total)
    for line in svc.order_lines_of(o):
        if line["status"] == "ALLOCATED":
            product = db.products.get(line["product_id"])
            if product:
                product["qty_allocated"] -= line["qty"]
            line["status"] = "FULFILLED"
            svc.touch(line)
    o["status"] = "DELIVERED"
    svc.touch(o)
    if facility:
        svc.recompute_facility_ledger(facility)
    return success_object(dict(o))


@bp.post("/jansan/orders/<order_id>/invoice")
def invoice_order(order_id):
    require_roles("DistributorAdmin")
    o = get_order_or_404(order_id)
    if o["status"] != "DELIVERED":
        raise ApiError(ERR_INVALID_STATE, "Order is not DELIVERED", 409)
    o["status"] = "INVOICED"
    svc.touch(o)
    facility = db.facilities.get(o["facility_id"])
    if facility:
        svc.recompute_facility_ledger(facility)
    return success_object(dict(o))


@bp.post("/jansan/orders/<order_id>/cancel")
def cancel_order(order_id):
    user_id, role = require_roles(*WRITE_ROLES)
    o = get_order_or_404(order_id)
    check_facility_ownership(user_id, role, o["facility_id"])
    if o["status"] not in ("DRAFT", "PLACED", "PARTIALLY_BLOCKED"):
        raise ApiError(ERR_INVALID_STATE, "Order cannot be cancelled from current state", 409)
    facility = db.facilities.get(o["facility_id"])
    if facility is None or facility["status"] != "ACTIVE":
        raise ApiError(ERR_FACILITY_INACTIVE, "Facility is not ACTIVE", 409)
    was_committed = o["status"] in ("PLACED", "PARTIALLY_BLOCKED")
    for line in svc.order_lines_of(o):
        if line["status"] in ("PENDING", "ALLOCATED", "SUBSTITUTION_PENDING"):
            if line["status"] == "ALLOCATED":
                product = db.products.get(line["product_id"])
                if product:
                    product["qty_allocated"] -= line["qty"]
                    product["qty_on_hand"] += line["qty"]
            line["status"] = "CANCELLED"
            svc.touch(line)
            # PENDING proposals of cancelled lines -> DECLINED
            for prop in db.substitution_proposals.values():
                if prop["order_line_id"] == line["id"] and prop["status"] == "PENDING":
                    prop["status"] = "DECLINED"
                    svc.touch(prop)
    o["status"] = "CANCELLED"
    svc.touch(o)
    if was_committed and facility:
        svc.recompute_facility_ledger(facility)
    return success_object(dict(o))


# ---------------------------------------------------------------------------
# Order lines
# ---------------------------------------------------------------------------

@bp.get("/jansan/order-lines/<order_line_id>")
def get_order_line(order_line_id):
    user_id, role = require_roles(*READ_ROLES)
    line = db.order_lines.get(order_line_id)
    if line is None:
        raise not_found("Order line not found")
    order = db.orders.get(line["order_id"])
    if order is not None:
        check_facility_ownership(user_id, role, order["facility_id"])
    return success_object(dict(line))


@bp.get("/jansan/order-lines")
def list_order_lines():
    user_id, role = require_roles(*READ_ROLES)
    order_id = request.args.get("order_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    limit, offset = _pagination()
    items = list(db.order_lines.values())
    if role == "FacilityManager":
        items = [l for l in items
                 if db.orders.get(l["order_id"]) and db.orders[l["order_id"]]["facility_id"] == user_id]
    if order_id:
        items = [l for l in items if l["order_id"] == order_id]
    if product_id:
        items = [l for l in items if l["product_id"] == product_id]
    if status:
        items = [l for l in items if l["status"] == status]
    items.sort(key=lambda l: clock.parse_iso(l["created_at"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([dict(l) for l in page], limit, offset, total)
