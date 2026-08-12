from flask import Blueprint, request

from db import store, touch
from errors import (
    raise_err, ERR_SUBSCRIPTION_NOT_FOUND, ERR_SHIPMENT_NOT_FOUND,
    ERR_SUBSCRIPTION_NOT_ACTIVE, ERR_PRODUCT_NOT_FOUND, ERR_PRODUCT_INACTIVE,
    ERR_DELIVERY_WINDOW_CONFLICT, ERR_INVALID_FULFILLMENT_TRANSITION,
    ERR_INVALID_REQUEST,
)
from middleware import get_body, authenticate, check_ownership, paginate, sort_items
from response import ok, ok_list
from serializers import ser_shipment
from services import (
    find_product_by_sku, create_box, create_invoice, deliver_cascade,
)
from util import req_str, req_enum, parse_dt

bp = Blueprint("shipments", __name__)

READ_ROLES = ["Customer", "Agronomist", "FulfillmentOps", "PlatformAdmin"]
NEXT_STATE = {"SCHEDULED": "PICKING", "PICKING": "SHIPPED", "SHIPPED": "DELIVERED"}


def _validate_lines(lines):
    if not isinstance(lines, list) or not lines:
        raise_err(ERR_INVALID_REQUEST, "Field 'lines' must be a non-empty array")
    for line in lines:
        if not isinstance(line, dict):
            raise_err(ERR_INVALID_REQUEST, "Each box line must be an object")
        sku = line.get("product_sku")
        if not isinstance(sku, str) or not sku.strip():
            raise_err(ERR_INVALID_REQUEST, "Each box line requires a 'product_sku' string")
        qty = line.get("qty_units")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise_err(ERR_INVALID_REQUEST, "Each box line requires 'qty_units' as a positive integer")


@bp.route("/api/shipments", methods=["POST"])
def create_shipment():
    body = get_body()
    subscription_id = req_str(body, "subscription_id")
    box_kind = req_enum(body, "box_kind", {"SEASONAL", "ADDON", "REPLACEMENT"})
    if box_kind == "REPLACEMENT":
        # REPLACEMENT boxes are minted only by claim resolution (PRD 3.6)
        raise_err(ERR_INVALID_REQUEST, "box_kind REPLACEMENT cannot be created directly")
    ship_raw = body.get("ship_date")
    if ship_raw is None:
        raise_err(ERR_INVALID_REQUEST, "Field 'ship_date' is required")
    ship_date = parse_dt(ship_raw, "ship_date")
    dws_raw = body.get("delivery_window_start")
    dwe_raw = body.get("delivery_window_end")
    if dws_raw is None or dwe_raw is None:
        raise_err(ERR_INVALID_REQUEST,
                  "Fields 'delivery_window_start' and 'delivery_window_end' are required")
    dw_start = parse_dt(dws_raw, "delivery_window_start")
    dw_end = parse_dt(dwe_raw, "delivery_window_end")
    if dw_end <= dw_start:
        raise_err(ERR_INVALID_REQUEST, "delivery_window_end must be after delivery_window_start")
    if "lines" not in body:
        raise_err(ERR_INVALID_REQUEST, "Field 'lines' is required")
    lines = body["lines"]
    _validate_lines(lines)

    authenticate(["FulfillmentOps", "PlatformAdmin"])

    sub = store.subscriptions.get(subscription_id)
    if sub is None:
        raise_err(ERR_SUBSCRIPTION_NOT_FOUND, "Subscription not found")
    # body FK existence band: every sku must resolve
    for line in lines:
        if find_product_by_sku(line["product_sku"]) is None:
            raise_err(ERR_PRODUCT_NOT_FOUND,
                      "Box line sku '%s' does not exist in the catalog" % line["product_sku"])
    if sub.status != "ACTIVE":
        raise_err(ERR_SUBSCRIPTION_NOT_ACTIVE, "Box creation requires subscription ACTIVE")
    for line in lines:
        if not find_product_by_sku(line["product_sku"]).active:
            raise_err(ERR_PRODUCT_INACTIVE, "Box line sku '%s' is inactive" % line["product_sku"])
    # delivery-window overlap against other non-terminal boxes (half-open intervals;
    # adjacency allowed)
    for other in store.shipments.values():
        if other.subscription_id != subscription_id:
            continue
        if other.fulfillment_status in ("DELIVERED", "SKIPPED", "CANCELLED"):
            continue
        if dw_start < other.delivery_window_end and other.delivery_window_start < dw_end:
            raise_err(ERR_DELIVERY_WINDOW_CONFLICT,
                      "Delivery window overlaps another non-terminal box on this subscription")

    box = create_box(
        subscription_id, box_kind, ship_date, dw_start, dw_end, lines,
        raw={"ship_date": ship_raw,
             "delivery_window_start": dws_raw,
             "delivery_window_end": dwe_raw},
    )
    return ok(ser_shipment(box), 201)


@bp.route("/api/shipments/<bid>", methods=["GET"])
def get_shipment(bid):
    uid, role = authenticate(READ_ROLES)
    box = store.shipments.get(bid)
    if box is None:
        raise_err(ERR_SHIPMENT_NOT_FOUND, "Shipment not found")
    sub = store.subscriptions.get(box.subscription_id)
    check_ownership(uid, role, sub.customer_id if sub else None)
    return ok(ser_shipment(box))


@bp.route("/api/shipments", methods=["GET"])
def list_shipments():
    uid, role = authenticate(READ_ROLES)
    items = list(store.shipments.values())
    if role == "Customer":
        own_subs = {s.id for s in store.subscriptions.values() if s.customer_id == uid}
        items = [b for b in items if b.subscription_id in own_subs]
    for param, attr in (("subscription_id", "subscription_id"),
                        ("source_claim_id", "source_claim_id"),
                        ("fulfillment_status", "fulfillment_status"),
                        ("box_kind", "box_kind")):
        v = request.args.get(param)
        if v is not None:
            items = [b for b in items if getattr(b, attr) == v]
    items = sort_items(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_shipment(b) for b in page], total, limit, offset)


@bp.route("/api/shipments/<bid>/advance-fulfillment", methods=["POST"])
def advance_fulfillment(bid):
    body = get_body()
    to_status = req_enum(
        body, "to_status",
        {"SCHEDULED", "PICKING", "SHIPPED", "DELIVERED", "HELD", "SKIPPED", "CANCELLED"},
    )
    authenticate(["FulfillmentOps"])
    box = store.shipments.get(bid)
    if box is None:
        raise_err(ERR_SHIPMENT_NOT_FOUND, "Shipment not found")

    expected_next = NEXT_STATE.get(box.fulfillment_status)
    if to_status != expected_next:
        raise_err(ERR_INVALID_FULFILLMENT_TRANSITION,
                  "to_status must be the immediate next fulfillment state")
    sub = store.subscriptions.get(box.subscription_id)
    if to_status in ("PICKING", "SHIPPED"):
        if sub is None or sub.status != "ACTIVE":
            raise_err(ERR_SUBSCRIPTION_NOT_ACTIVE,
                      "Advancing fulfillment requires subscription ACTIVE")

    box.fulfillment_status = to_status
    if to_status == "SHIPPED":
        box.billing_status = "INVOICED"
        create_invoice(box)
    elif to_status == "DELIVERED":
        deliver_cascade(box)
    touch(box)
    return ok(ser_shipment(box))
