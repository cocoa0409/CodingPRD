"""DSD receiving: shipments and shipment lines."""
from flask import Blueprint, request, g

from auth import require_role
from common import (
    stamp_new, touch, require_dict, get_str, get_int, get_dt,
    pagination_params, paginate,
)
from db import db
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_DUPLICATE_RESOURCE,
    ERR_SHIPMENT_NOT_PENDING, ERR_SHIPMENT_EMPTY, ERR_SHIPMENT_NOT_RECEIVING,
    ERR_PRODUCT_DISCONTINUED, ERR_RECEIVE_VARIANCE_EXCEEDED, ERR_STALE_PRODUCT_VERSION,
)
from lookup import get_shipment, get_shipment_line, get_product
from inventory import product_inventory_rollup
from response import success, list_response
from serializers import ser_shipment, ser_shipment_line

bp = Blueprint("receiving", __name__)

RECEIVE_VARIANCE_TOLERANCE_BPS = 500


def _line_cost(product, qty, unit_cost):
    if product is not None and product["sell_by_weight"]:
        from common import round_half_up
        return round_half_up(qty * unit_cost, 1000)
    return qty * unit_cost


# ---------------- Shipments ----------------

@bp.route("/shipments", methods=["POST"])
def create_shipment():
    require_role("ReceivingClerk", "StoreManager")
    body = require_dict(request.get_json(silent=True))
    vendor = get_str(body, "vendor_name")
    ref = get_str(body, "reference_code")
    expected = get_int(body, "expected_total_cents", min_value=0)
    for s in db.shipments.values():
        if s["reference_code"] == ref:
            raise ApiError(ERR_DUPLICATE_RESOURCE[0], ERR_DUPLICATE_RESOURCE[1], "reference_code already exists")
    rec = stamp_new({
        "vendor_name": vendor,
        "reference_code": ref,
        "expected_total_cents": expected,
        "status": "PENDING",
    })
    db.shipments[rec["id"]] = rec
    return success(ser_shipment(rec), status=201)


@bp.route("/shipments", methods=["GET"])
def list_shipments():
    require_role("ReceivingClerk", "StoreManager", "InventoryAuditor")
    limit, offset = pagination_params(request.args)
    items = list(db.shipments.values())
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response([ser_shipment(s) for s in page], limit, offset, total)


@bp.route("/shipments/<sid>", methods=["GET"])
def get_shipment_route(sid):
    require_role("ReceivingClerk", "StoreManager", "InventoryAuditor")
    s = get_shipment(sid)
    return success(ser_shipment(s))


@bp.route("/shipments/<sid>/lines", methods=["POST"])
def add_shipment_line(sid):
    require_role("ReceivingClerk", "StoreManager")
    s = get_shipment(sid)
    body = require_dict(request.get_json(silent=True))
    # FK existence first
    product_id = body.get("product_id")
    if not isinstance(product_id, str) or not product_id:
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "product_id is required")
    product = get_product(product_id)

    ordered = get_int(body, "ordered_qty", min_value=1)  # > 0
    unit_cost = get_int(body, "unit_cost_cents", min_value=0)
    accepted = get_int(body, "accepted_qty", required=False, default=None, min_value=0)
    if accepted is None:
        accepted = ordered

    exp_str = None
    exp_dt = None
    if product["is_perishable"]:
        exp_dt = get_dt(body, "expiration_date")  # required for perishable
        exp_str = body["expiration_date"]
    else:
        if body.get("expiration_date") is not None:
            exp_dt = get_dt(body, "expiration_date", required=False)
            exp_str = body["expiration_date"]

    # State: line added while shipment PENDING
    if s["status"] != "PENDING":
        raise ApiError(ERR_SHIPMENT_NOT_PENDING[0], ERR_SHIPMENT_NOT_PENDING[1], "shipment not pending")

    rec = stamp_new({
        "shipment_id": sid,
        "product_id": product_id,
        "ordered_qty": ordered,
        "accepted_qty": accepted,
        "unit_cost_cents": unit_cost,
        "expiration_date": exp_str,
        "status": "OPEN",
        "_expiration_dt": exp_dt,
    })
    db.shipment_lines[rec["id"]] = rec
    return success(ser_shipment_line(rec), status=201)


@bp.route("/shipment-lines/<lid>", methods=["GET"])
def get_shipment_line_route(lid):
    require_role("ReceivingClerk", "StoreManager", "InventoryAuditor")
    line = get_shipment_line(lid)
    return success(ser_shipment_line(line))


@bp.route("/shipment-lines", methods=["GET"])
def list_shipment_lines():
    require_role("ReceivingClerk", "StoreManager", "InventoryAuditor")
    limit, offset = pagination_params(request.args)
    items = list(db.shipment_lines.values())
    shipment_id = request.args.get("shipment_id")
    if shipment_id is not None:
        items = [l for l in items if l["shipment_id"] == shipment_id]
    product_id = request.args.get("product_id")
    if product_id is not None:
        items = [l for l in items if l["product_id"] == product_id]
    status = request.args.get("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response([ser_shipment_line(l) for l in page], limit, offset, total)


def _lines_of(sid):
    return [l for l in db.shipment_lines.values() if l["shipment_id"] == sid]


@bp.route("/shipments/<sid>/start-receiving", methods=["POST"])
def start_receiving(sid):
    require_role("ReceivingClerk")
    s = get_shipment(sid)
    if s["status"] != "PENDING":
        raise ApiError(ERR_SHIPMENT_NOT_PENDING[0], ERR_SHIPMENT_NOT_PENDING[1], "shipment not pending")
    open_lines = [l for l in _lines_of(sid) if l["status"] == "OPEN"]
    if len(open_lines) < 1:
        raise ApiError(ERR_SHIPMENT_EMPTY[0], ERR_SHIPMENT_EMPTY[1], "shipment has no open lines")
    s["status"] = "RECEIVING"
    touch(s)
    return success(ser_shipment(s))


@bp.route("/shipments/<sid>/receive", methods=["POST"])
def receive_shipment(sid):
    role = g.role
    require_role("ReceivingClerk", "StoreManager")
    s = get_shipment(sid)
    body = require_dict(request.get_json(silent=True))
    expected_version = get_int(body, "expected_product_version")
    override_variance = body.get("override_variance", False)
    if override_variance is not None and not isinstance(override_variance, bool):
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "override_variance must be a boolean")
    override_variance = bool(override_variance)

    # State (priority 6)
    if s["status"] != "RECEIVING":
        raise ApiError(ERR_SHIPMENT_NOT_RECEIVING[0], ERR_SHIPMENT_NOT_RECEIVING[1], "shipment not receiving")

    lines = _lines_of(sid)
    # Every referenced product ACTIVE
    for line in lines:
        product = db.products.get(line["product_id"])
        if product is not None and product["status"] != "ACTIVE":
            raise ApiError(ERR_PRODUCT_DISCONTINUED[0], ERR_PRODUCT_DISCONTINUED[1], "shipment line targets discontinued product")

    # Compute received total for the variance gate
    received_total = 0
    for line in lines:
        product = db.products.get(line["product_id"])
        received_total += _line_cost(product, line["accepted_qty"], line["unit_cost_cents"])
    expected_total = s["expected_total_cents"]

    # Variance gate (priority 12)
    exceeded = False
    if expected_total == 0:
        exceeded = received_total != 0
    else:
        scaled = abs(received_total - expected_total) * 10000 // expected_total
        exceeded = scaled > RECEIVE_VARIANCE_TOLERANCE_BPS
    if exceeded:
        if not (override_variance and role == "StoreManager"):
            raise ApiError(ERR_RECEIVE_VARIANCE_EXCEEDED[0], ERR_RECEIVE_VARIANCE_EXCEEDED[1], "receive variance exceeded")

    # OCC (priority 13): guard against the product of the first line (earliest created_at)
    first_line = None
    if lines:
        first_line = sorted(lines, key=lambda l: (l["created_at"], l.get("_seq", 0)))[0]
    if first_line is not None:
        occ_product = db.products.get(first_line["product_id"])
        if occ_product is not None and expected_version != occ_product["version"]:
            raise ApiError(ERR_STALE_PRODUCT_VERSION[0], ERR_STALE_PRODUCT_VERSION[1], "stale product version")

    # Success path: create lots, recompute, bump versions
    affected_products = {}
    for line in lines:
        if line["accepted_qty"] > 0:
            product = db.products.get(line["product_id"])
            lot = stamp_new({
                "product_id": line["product_id"],
                "shipment_id": sid,
                "received_qty": line["accepted_qty"],
                "remaining_qty": line["accepted_qty"],
                "unit_cost_cents": line["unit_cost_cents"],
                "expiration_date": line["expiration_date"],
                "status": "ACTIVE",
                "_expiration_dt": line.get("_expiration_dt"),
            })
            db.inventory_lots[lot["id"]] = lot
            if product is not None:
                affected_products[product["id"]] = product
        # line status: ACCEPTED if accepted == ordered else SHORT
        line["status"] = "ACCEPTED" if line["accepted_qty"] == line["ordered_qty"] else "SHORT"
        touch(line)

    for product in affected_products.values():
        product_inventory_rollup(product)
        touch(product)

    s["status"] = "RECEIVED"
    touch(s)
    return success(ser_shipment(s))


@bp.route("/shipments/<sid>/reject", methods=["POST"])
def reject_shipment(sid):
    require_role("ReceivingClerk", "StoreManager")
    s = get_shipment(sid)
    if s["status"] != "RECEIVING":
        raise ApiError(ERR_SHIPMENT_NOT_RECEIVING[0], ERR_SHIPMENT_NOT_RECEIVING[1], "shipment not receiving")
    # All lines remain OPEN; no lots; no inventory change
    s["status"] = "REJECTED"
    touch(s)
    return success(ser_shipment(s))
