"""Shipment endpoints (PRD §3.7, §3.8)."""
import random
import string

from flask import Blueprint, request

from db import store, new_id, stamp_create, touch
from errors import err
from middleware import get_auth, require_roles
from response import success
from common import (
    get_client, get_order, get_shipment,
    get_json_body, parse_pagination, paginate,
)
from serializers import serialize_shipment
import calc
from services import order_ops

bp = Blueprint("shipments", __name__)

READ_ROLES = {"ShipStation", "BillingClerk", "ClientUser"}
ALL_CARRIERS = ["GROUND_ECONOMY", "GROUND_PLUS", "AIR_EXPRESS"]


def _mint_tracking():
    return "TRK" + "".join(random.choices(string.ascii_uppercase + string.digits, k=15))


def _order_has_hazmat(order):
    for line in order["lines"]:
        sku = store.skus.get(line["sku_id"])
        if sku is not None and sku.get("hazmat"):
            return True
    return False


@bp.route("/clients/<client_id>/shipments", methods=["POST"])
def create_shipment(client_id):
    _, role = get_auth()
    require_roles(role, {"ShipStation"})
    get_client(client_id)
    body = get_json_body()

    order_id = body.get("order_id")
    if not isinstance(order_id, str) or order_id == "":
        raise err("ERR_INVALID_REQUEST", "order_id is required")

    order = get_order(order_id)
    if order["client_id"] != client_id:
        raise err("ERR_CLIENT_OWNERSHIP_MISMATCH", "Order not owned by path client")

    if order["status"] != "PACKED":
        raise err("ERR_ORDER_NOT_PACKED", "Order is not PACKED")

    force_carrier = body.get("force_carrier")
    if force_carrier is not None and force_carrier not in ALL_CARRIERS:
        raise err("ERR_INVALID_REQUEST", "force_carrier is not a known carrier")

    has_hazmat = _order_has_hazmat(order)
    carton_count = len(order_ops.cartons_for_order(order_id, statuses={"PACKED"}))
    client = store.clients[client_id]
    discount_bps = client["carrier_discount_bps"]
    zone = order["ship_to_zone"]

    if force_carrier is not None:
        # Explicit override: hazmat + GROUND_ECONOMY is forbidden.
        if force_carrier == "GROUND_ECONOMY" and has_hazmat:
            raise err("ERR_HAZMAT_CARRIER_FORBIDDEN", "GROUND_ECONOMY forbidden for hazmat order")
        carrier = force_carrier
        published = calc.published_quote_cents(carrier, zone, carton_count)
        quoted = calc.negotiated_quote_cents(published, discount_bps)
    else:
        # Eligibility filter then ranking on negotiated quote.
        eligible = set(ALL_CARRIERS)
        if has_hazmat:
            eligible.discard("GROUND_ECONOMY")
        carrier, quoted = calc.rate_shop(eligible, zone, carton_count, discount_bps)

    rec = stamp_create({
        "id": new_id(),
        "order_id": order_id,
        "carrier": carrier,
        "quoted_cost_cents": quoted,
        "tracking_number": _mint_tracking(),
        "status": "LABELLED",
    })
    store.shipments[rec["id"]] = rec
    return success(serialize_shipment(rec), status=201)


@bp.route("/shipments", methods=["GET"])
def list_shipments():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    limit, offset = parse_pagination()
    items = list(store.shipments.values())
    order_id = request.args.get("order_id")
    if order_id is not None:
        items = [s for s in items if s["order_id"] == order_id]
    page, meta = paginate(items, limit, offset)
    return success([serialize_shipment(r) for r in page], pagination=meta)


@bp.route("/shipments/<shipment_id>", methods=["GET"])
def get_one_shipment(shipment_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    rec = get_shipment(shipment_id)
    return success(serialize_shipment(rec))


def _resolve_shipment(client_id, shipment_id):
    get_client(client_id)
    rec = get_shipment(shipment_id)
    order = store.orders.get(rec["order_id"])
    if order is None or order["client_id"] != client_id:
        raise err("ERR_CLIENT_OWNERSHIP_MISMATCH", "Shipment not owned by path client")
    return rec, order


@bp.route("/clients/<client_id>/shipments/<shipment_id>/deliver", methods=["POST"])
def deliver_shipment(client_id, shipment_id):
    _, role = get_auth()
    require_roles(role, {"ShipStation"})
    rec, order = _resolve_shipment(client_id, shipment_id)

    if rec["status"] != "LABELLED":
        raise err("ERR_SHIPMENT_NOT_LABELLED", "Shipment is not LABELLED")
    if order["status"] != "SHIPPED":
        raise err("ERR_ORDER_NOT_SHIPPED", "Order is not SHIPPED")

    rec["status"] = "DELIVERED"
    touch(rec)
    return success(serialize_shipment(rec))


@bp.route("/clients/<client_id>/shipments/<shipment_id>/void", methods=["POST"])
def void_shipment(client_id, shipment_id):
    _, role = get_auth()
    require_roles(role, {"ShipStation"})
    rec, order = _resolve_shipment(client_id, shipment_id)

    if rec["status"] != "LABELLED":
        raise err("ERR_SHIPMENT_NOT_LABELLED", "Shipment is not LABELLED")
    if order["status"] != "PACKED":
        raise err("ERR_ORDER_NOT_PACKED", "Order is not PACKED")

    rec["status"] = "VOIDED"
    touch(rec)
    return success(serialize_shipment(rec))
