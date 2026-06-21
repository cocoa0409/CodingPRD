"""Order line routes (PRD §3.2, §3.7 produce)."""

from flask import Blueprint, request, g

import db
import errors
from errors import err
from middleware import require_roles
from response import object_response, array_response
from services import serialize
from services import pricing
from services.ownership import require_order_owner
from services.common import (
    get_body, require_fields, require_int, require_str, lookup, list_collection,
)

bp = Blueprint("order_lines", __name__)


def _validate_finishing_codes(product_id, codes):
    """Each code must name a finishing option belonging to product_id
    (ERR_FINISHING_NOT_FOR_PRODUCT, 422)."""
    valid = {opt["code"] for opt in db.finishing_options.values()
             if opt["product_id"] == product_id}
    for code in codes:
        if code not in valid:
            raise err(errors.ERR_FINISHING_NOT_FOR_PRODUCT,
                      "Finishing code %s does not belong to product %s"
                      % (code, product_id))


def _normalize_codes(body):
    codes = body.get("finishing_codes", [])
    if codes is None:
        codes = []
    if not isinstance(codes, list) or any(not isinstance(c, str) for c in codes):
        raise err(errors.ERR_VALIDATION, "finishing_codes must be an array of strings")
    return codes


@bp.post("/order-lines")
@require_roles("ShopStaff", "Customer")
def create_order_line():
    body = get_body()
    require_fields(body, "order_id", "product_id", "quantity")
    order_id = require_str(body, "order_id")
    # Existence left-to-right: order then product (PRD §2.5).
    order = lookup(db.orders, order_id)
    product_id = require_str(body, "product_id")
    product = lookup(db.products, product_id)

    # Ownership (403) before state/business checks (PRD §3.9).
    require_order_owner(order)

    quantity = require_int(body, "quantity", min_value=1)
    codes = _normalize_codes(body)
    service_level = body.get("service_level", "STANDARD")
    if service_level is None:
        service_level = "STANDARD"
    if service_level not in ("STANDARD", "RUSH"):
        raise err(errors.ERR_VALIDATION, "service_level must be STANDARD or RUSH")

    # Business checks in scaffold priority order: finishing-belongs (422) then
    # product-active (409).
    _validate_finishing_codes(product_id, codes)
    if not product["active"]:
        raise err(errors.ERR_PRODUCT_INACTIVE,
                  "Product %s is inactive" % product_id)

    estimate = pricing.compute_line_price(product, quantity, codes)
    units = pricing.production_units(product, quantity)

    rec = {
        "order_id": order_id,
        "product_id": product_id,
        "quantity": quantity,
        "finishing_codes": list(codes),
        "service_level": service_level,
        "status": "OPEN",
        "production_units": units,
        "estimate_line_cents": estimate,
        "final_line_cents": None,
        "rush_surcharge_cents": 0,
        "promised_ready_date": None,
    }
    db.stamp_new(rec)
    db.order_lines[rec["id"]] = rec
    return object_response(serialize.order_line(rec), 201)


@bp.get("/order-lines")
@require_roles("ShopStaff", "ProductionOperator", "Customer")
def list_order_lines():
    order_id = request.args.get("order_id")
    product_id = request.args.get("product_id")

    def pred(r):
        if order_id is not None and r["order_id"] != order_id:
            return False
        if product_id is not None and r["product_id"] != product_id:
            return False
        return True

    items, limit, offset, total = list_collection(db.order_lines, pred)
    return array_response([serialize.order_line(r) for r in items], limit, offset, total)


@bp.get("/order-lines/<order_line_id>")
@require_roles("ShopStaff", "ProductionOperator", "Customer")
def read_order_line(order_line_id):
    rec = lookup(db.order_lines, order_line_id)
    return object_response(serialize.order_line(rec), 200)


@bp.patch("/order-lines/<order_line_id>")
@require_roles("ShopStaff", "Customer")
def edit_order_line(order_line_id):
    line = lookup(db.order_lines, order_line_id)
    order = lookup(db.orders, line["order_id"])
    require_order_owner(order)

    # Only OPEN or PREFLIGHT_OK lines may be edited (PRD §3.2).
    if line["status"] not in ("OPEN", "PREFLIGHT_OK"):
        raise err(errors.ERR_INVALID_STATE,
                  "Line in status %s cannot be edited" % line["status"])

    body = get_body()
    product = db.products[line["product_id"]]

    new_quantity = line["quantity"]
    if "quantity" in body and body["quantity"] is not None:
        new_quantity = require_int(body, "quantity", min_value=1)

    new_codes = line["finishing_codes"]
    if "finishing_codes" in body:
        new_codes = _normalize_codes(body)
        _validate_finishing_codes(line["product_id"], new_codes)

    new_service = line["service_level"]
    if "service_level" in body and body["service_level"] is not None:
        new_service = body["service_level"]
        if new_service not in ("STANDARD", "RUSH"):
            raise err(errors.ERR_VALIDATION, "service_level must be STANDARD or RUSH")

    line["quantity"] = new_quantity
    line["finishing_codes"] = list(new_codes)
    line["service_level"] = new_service
    # Recompute estimate_line_cents and production_units on each edit (PRD §3.2).
    line["estimate_line_cents"] = pricing.compute_line_price(product, new_quantity, new_codes)
    line["production_units"] = pricing.production_units(product, new_quantity)
    db.touch(line)
    return object_response(serialize.order_line(line), 200)


@bp.post("/order-lines/<order_line_id>/produce")
@require_roles("ProductionOperator")
def produce_line(order_line_id):
    line = lookup(db.order_lines, order_line_id)
    order = lookup(db.orders, line["order_id"])

    # State: line must be PRICE_LOCKED and order IN_PRODUCTION (PRD §3.7).
    if line["status"] != "PRICE_LOCKED" or order["production_status"] != "IN_PRODUCTION":
        raise err(errors.ERR_INVALID_STATE,
                  "Line must be PRICE_LOCKED and order IN_PRODUCTION to produce")

    line["status"] = "PRODUCED"
    db.touch(line)

    # When ALL lines of the order are PRODUCED, bubble up IN_PRODUCTION -> READY.
    siblings = [l for l in db.order_lines.values() if l["order_id"] == order["id"]]
    if siblings and all(l["status"] == "PRODUCED" for l in siblings):
        order["production_status"] = "READY"
        db.touch(order)

    return object_response(serialize.order_line(line), 200)
