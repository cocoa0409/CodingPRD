"""Shipment endpoints."""

from flask import Blueprint

import errors as E
import middleware as M
import response as R
import services as S
from db import store, new_id, stamp_created, touch

bp = Blueprint("shipments", __name__)

READ_ROLES = S.ALL_ROLES
WAREHOUSE_ONLY = {"WarehouseOperator"}
METHODS = {"GROUND", "AIR"}


@bp.post("/api/orders/<oid>/shipments")
def create_shipment(oid):
    ctx = M.require_auth()
    data = M.body()
    M.no_unknown(data, {"method", "items"})
    method = M.req_enum(data, "method", METHODS)
    items_raw = data.get("items")
    if items_raw is None:
        raise E.invalid_request("Missing required field: items")
    if not isinstance(items_raw, list):
        raise E.invalid_request("Field items must be an array")
    parsed = []
    for el in items_raw:
        if not isinstance(el, dict):
            raise E.invalid_request("Each shipment item must be an object")
        M.no_unknown(el, {"order_item_id", "quantity"})
        oi_id = M.req_string(el, "order_item_id")
        qty = M.req_pos_int(el, "quantity")
        parsed.append({"order_item_id": oi_id, "quantity": qty})
    M.require_role(ctx, WAREHOUSE_ONLY)
    order = S.get_order(oid)
    if order["fulfillment_status"] not in ("APPROVED", "FULFILLING"):
        raise E.invalid_order_state("Shipments require an APPROVED or FULFILLING order")

    order_items = {i["id"]: i for i in S.items_of_order(order["id"])}

    # priority 8: hazmat / method pairing (resolvable items only)
    hazmat_involved = False
    for el in parsed:
        item = order_items.get(el["order_item_id"])
        if item is None:
            continue
        product = store.products.get(item["product_id"])
        if product is not None and product["hazmat_class"] != "NONE":
            hazmat_involved = True
    if hazmat_involved and method == "AIR":
        raise E.hazmat_air_forbidden()

    # priority 9: diversion hold on the order's salon
    for case in store.diversion_cases.values():
        if (case["salon_account_id"] == order["salon_account_id"]
                and case["status"] in ("OPEN", "UNDER_REVIEW") and case["hold_shipments"]):
            raise E.shipment_held_diversion()

    # priority 10: item references and per-line quantities over non-voided shipments
    requested = {}
    for el in parsed:
        item = order_items.get(el["order_item_id"])
        if item is None:
            raise E.shipment_quantity_exceeds("Shipment references an item of another order")
        requested[item["id"]] = requested.get(item["id"], 0) + el["quantity"]
    already = {}
    for s in S.shipments_of_order(order["id"]):
        if s.get("_voided", False):
            continue
        for el in s["items"]:
            already[el["order_item_id"]] = already.get(el["order_item_id"], 0) + el["quantity"]
    for item_id, qty in requested.items():
        if already.get(item_id, 0) + qty > order_items[item_id]["quantity"]:
            raise E.shipment_quantity_exceeds("Per-item shipped quantity exceeds ordered quantity")

    # charges (calculations.hazmat_shipping_charge)
    hazmat_grams = 0
    for el in parsed:
        item = order_items[el["order_item_id"]]
        product = store.products.get(item["product_id"])
        if product is not None and product["hazmat_class"] != "NONE":
            hazmat_grams += el["quantity"] * product["weight_grams"]
    if hazmat_grams > 0:
        surcharge = S.HAZMAT_FLAT_CENTS + S.HAZMAT_PER_GRAM_CENTS * hazmat_grams
        declaration = True
    else:
        surcharge = 0
        declaration = False
    charge = S.METHOD_BASE_CENTS[method] + surcharge

    shipment = {
        "id": new_id(),
        "order_id": order["id"],
        "method": method,
        "items": parsed,
        "status": "PLANNED",
        "hazmat_declaration_required": declaration,
        "hazmat_surcharge_cents": surcharge,
        "shipping_charge_cents": charge,
        "_voided": False,
    }
    stamp_created(shipment)
    store.shipments[shipment["id"]] = shipment
    if order["fulfillment_status"] == "APPROVED":
        order["fulfillment_status"] = "FULFILLING"
    S.recompute_order_totals(order)
    touch(order)
    return R.success_object(S.pub(shipment), 201)


@bp.get("/api/orders/<oid>/shipments")
def list_shipments(oid):
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    order = S.get_order(oid)
    S.read_scope_order(ctx, order)
    items = S.shipments_of_order(order["id"])
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.pub_list(page), limit, offset, total)


@bp.get("/api/shipments/<sid>")
def get_shipment(sid):
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    shipment = S.get_shipment(sid)
    order = store.orders.get(shipment["order_id"])
    if order is not None:
        S.read_scope_order(ctx, order)
    return R.success_object(S.pub(shipment))


@bp.post("/api/shipments/<sid>/create-label")
def create_label(sid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, WAREHOUSE_ONLY)
    shipment = S.get_shipment(sid)
    if shipment["status"] != "PLANNED":
        raise E.invalid_shipment_state("Only a PLANNED shipment can get a label")
    was_voided = shipment.get("_voided", False)
    shipment["status"] = "LABEL_CREATED"
    shipment["_voided"] = False
    touch(shipment)
    if was_voided:
        order = store.orders.get(shipment["order_id"])
        if order is not None:
            S.recompute_order_totals(order)
            touch(order)
    return R.success_object(S.pub(shipment))


@bp.post("/api/shipments/<sid>/void-label")
def void_label(sid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, WAREHOUSE_ONLY)
    shipment = S.get_shipment(sid)
    if shipment["status"] != "LABEL_CREATED":
        raise E.invalid_shipment_state("Only a LABEL_CREATED shipment can be voided")
    shipment["status"] = "PLANNED"
    shipment["_voided"] = True
    touch(shipment)
    order = store.orders.get(shipment["order_id"])
    if order is not None:
        S.recompute_order_totals(order)
        touch(order)
    return R.success_object(S.pub(shipment))


@bp.post("/api/shipments/<sid>/ship")
def ship_shipment(sid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, WAREHOUSE_ONLY)
    shipment = S.get_shipment(sid)
    if shipment["status"] != "LABEL_CREATED":
        raise E.invalid_shipment_state("Only a LABEL_CREATED shipment can ship")
    shipment["status"] = "IN_TRANSIT"
    touch(shipment)
    order = store.orders.get(shipment["order_id"])
    if order is not None:
        S.maybe_mark_shipped(order)
    return R.success_object(S.pub(shipment))


@bp.post("/api/shipments/<sid>/deliver")
def deliver_shipment(sid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, WAREHOUSE_ONLY)
    shipment = S.get_shipment(sid)
    if shipment["status"] != "IN_TRANSIT":
        raise E.invalid_shipment_state("Only an IN_TRANSIT shipment can be delivered")
    shipment["status"] = "DELIVERED"
    touch(shipment)
    order = store.orders.get(shipment["order_id"])
    if order is not None:
        S.maybe_mark_delivered(order)
    return R.success_object(S.pub(shipment))
