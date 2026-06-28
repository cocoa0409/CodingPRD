"""Order routes: draft/lines/place/ready/fulfill/cancel (PRD §3.3, §3.5, §3.6)."""

from flask import Blueprint, request, g

import errors
from db import db, new_id, now_ts
from helpers import get_body, parse_pagination, paginate, as_int, as_str, as_enum
from middleware import require_roles
from response import success, list_success
from routes.common import get_or_404, require_owner
from services import serializers, pricing
from services.inventory import find_row, reserve, commit, release
from clock import clock, parse_iso8601

bp = Blueprint("orders", __name__)

FULFILLMENT_TYPES = {"BOPIS", "SFS"}


def _touch(rec):
    rec["updated_at"] = now_ts()
    rec["version"] += 1


def _lines_for(order_id):
    lines = [l for l in db.order_lines.values() if l["order_id"] == order_id]
    lines.sort(key=lambda l: (l["created_at"], l.get("_seq", 0)))
    return lines


# ---------------------------------------------------------------------------
# Create / read / list
# ---------------------------------------------------------------------------
@bp.route("/orders", methods=["POST"])
@require_roles("Customer")
def create_order():
    body = get_body()
    customer_id = as_str(body, "customer_id", required=True)
    store_id = as_str(body, "store_id", required=True)
    fulfillment_type = as_enum(body, "fulfillment_type", FULFILLMENT_TYPES, required=True)
    # Ownership (priority 3) before existence (priority 4) per §2.10.
    require_owner(customer_id)
    get_or_404(db.customers, customer_id)
    get_or_404(db.stores, store_id)

    ts = now_ts()
    rid = new_id()
    rec = {
        "id": rid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
        "customer_id": customer_id,
        "store_id": store_id,
        "fulfillment_type": fulfillment_type,
        "payment_status": "UNPAID",
        "fulfillment_status": "DRAFT",
        "provisional_total_cents": 0,
        "final_total_cents": None,
        "loyalty_points_awarded": 0,
    }
    db.orders[rid] = rec
    return success(serializers.order(rec), 201)


@bp.route("/orders/<rid>", methods=["GET"])
@require_roles("PlatformAdmin", "StoreAssociate", "PriceAdmin", "Customer")
def get_order(rid):
    rec = get_or_404(db.orders, rid)
    return success(serializers.order(rec), 200)


@bp.route("/orders", methods=["GET"])
@require_roles("PlatformAdmin", "StoreAssociate", "PriceAdmin", "Customer")
def list_orders():
    limit, offset = parse_pagination()
    customer_id = request.args.get("customer_id")
    store_id = request.args.get("store_id")
    items = list(db.orders.values())
    if customer_id is not None:
        items = [o for o in items if o["customer_id"] == customer_id]
    if store_id is not None:
        items = [o for o in items if o["store_id"] == store_id]
    page, total = paginate(items, limit, offset)
    return list_success([serializers.order(o) for o in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Lines
# ---------------------------------------------------------------------------
@bp.route("/orders/<rid>/lines", methods=["POST"])
@require_roles("Customer")
def add_order_line(rid):
    order = get_or_404(db.orders, rid)
    require_owner(order["customer_id"])
    body = get_body()
    sku_id = as_str(body, "sku_id", required=True)
    quantity = as_int(body, "quantity", required=True, minimum=1)
    embroidery_text = as_str(body, "embroidery_text", required=False, default=None)
    sku = get_or_404(db.skus, sku_id)

    # State: lines may only be added to a DRAFT order (§3.3).
    if order["fulfillment_status"] != "DRAFT":
        raise errors.invalid_state("Lines may only be added to a DRAFT order")

    # Business rule priority 7: embroidery only allowed on embroiderable SKUs.
    if embroidery_text is not None and not sku["embroiderable"]:
        raise errors.ApiError(errors.ERR_EMBROIDERY_NOT_ALLOWED, 422,
                              "embroidery_text is only allowed on embroiderable SKUs")
    # Business rule priority 8: footwear requires a non-NA size_label.
    if sku["is_footwear"] and sku["size_label"] == "NA":
        raise errors.ApiError(errors.ERR_FITMENT_REQUIRED, 422,
                              "Footwear line requires a non-NA size_label on the SKU")

    # Resolve store_inventory_id from order.store_id + sku_id (§3.3).
    row = find_row(order["store_id"], sku_id)
    store_inventory_id = row["id"] if row else None

    ts = now_ts()
    lid = new_id()
    line = {
        "id": lid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
        "order_id": rid,
        "sku_id": sku_id,
        "store_inventory_id": store_inventory_id,
        "quantity": quantity,
        "unit_price_cents": 0,
        "embroidery_text": embroidery_text,
        "line_status": "RESERVED",
    }
    db.order_lines[lid] = line
    return success(serializers.order_line(line), 201)


@bp.route("/orders/<rid>/lines", methods=["GET"])
@require_roles("PlatformAdmin", "StoreAssociate", "PriceAdmin", "Customer")
def list_order_lines_for_order(rid):
    get_or_404(db.orders, rid)
    limit, offset = parse_pagination()
    items = [l for l in db.order_lines.values() if l["order_id"] == rid]
    page, total = paginate(items, limit, offset)
    return list_success([serializers.order_line(l) for l in page], limit, offset, total)


@bp.route("/order-lines", methods=["GET"])
@require_roles("PlatformAdmin", "StoreAssociate", "PriceAdmin", "Customer")
def list_order_lines():
    limit, offset = parse_pagination()
    sku_id = request.args.get("sku_id")
    store_inventory_id = request.args.get("store_inventory_id")
    items = list(db.order_lines.values())
    if sku_id is not None:
        items = [l for l in items if l["sku_id"] == sku_id]
    if store_inventory_id is not None:
        items = [l for l in items if l["store_inventory_id"] == store_inventory_id]
    page, total = paginate(items, limit, offset)
    return list_success([serializers.order_line(l) for l in page], limit, offset, total)


@bp.route("/order-lines/<rid>", methods=["GET"])
@require_roles("PlatformAdmin", "StoreAssociate", "PriceAdmin", "Customer")
def get_order_line(rid):
    rec = get_or_404(db.order_lines, rid)
    return success(serializers.order_line(rec), 200)


# ---------------------------------------------------------------------------
# Place (DRAFT -> RESERVED)
# ---------------------------------------------------------------------------
@bp.route("/orders/<rid>/place", methods=["POST"])
@require_roles("Customer")
def place_order(rid):
    order = get_or_404(db.orders, rid)
    require_owner(order["customer_id"])

    # State (priority 6): place is only defined from DRAFT, with >=1 line and
    # payment UNPAID (§3.3).
    lines = _lines_for(rid)
    if order["fulfillment_status"] != "DRAFT" or order["payment_status"] != "UNPAID" or len(lines) == 0:
        raise errors.invalid_state("Order is not in a placeable state")

    customer = db.customers[order["customer_id"]]
    clock_dt = clock.now()

    # License gate (priority 9, §3.4) BEFORE inventory (priority 15).
    for line in lines:
        sku = db.skus[line["sku_id"]]
        if sku["requires_license_permit"]:
            if not _has_active_license(order["customer_id"], order["store_id"], clock_dt):
                raise errors.ApiError(errors.ERR_LICENSE_REQUIRED, 422,
                                      "Line requires a valid active fishing license at this store")

    # Inventory availability (priority 15). Aggregate per row across lines and
    # check all before committing any (atomicity).
    needed = {}
    for line in lines:
        row = find_row(order["store_id"], line["sku_id"])
        if row is None:
            raise errors.ApiError(errors.ERR_INSUFFICIENT_INVENTORY, 409,
                                  "No stock row for this store and SKU")
        needed[row["id"]] = needed.get(row["id"], 0) + line["quantity"]
    for row_id, qty in needed.items():
        row = db.store_inventory[row_id]
        if row["available_qty"] < qty:
            raise errors.ApiError(errors.ERR_INSUFFICIENT_INVENTORY, 409,
                                  "Insufficient available inventory")

    # RESERVE cascade: bump reserved_qty per line, recompute available.
    for line in lines:
        row = find_row(order["store_id"], line["sku_id"])
        line["store_inventory_id"] = row["id"]
        reserve(row, line["quantity"])
        # line stays RESERVED

    # Provisional total + per-line unit_price_cents capture (§3.6).
    order["provisional_total_cents"] = pricing.order_total_provisional(order, customer, clock_dt)
    # Payment axis UNPAID -> AUTHORIZED.
    order["payment_status"] = "AUTHORIZED"
    order["fulfillment_status"] = "RESERVED"
    _touch(order)
    return success(serializers.order(order), 200)


def _has_active_license(customer_id, store_id, clock_dt):
    for lic in db.fishing_licenses.values():
        if lic["customer_id"] != customer_id or lic["issuing_store_id"] != store_id:
            continue
        valid_until = parse_iso8601(lic["valid_until"])
        if clock_dt < valid_until:
            return True
    return False


# ---------------------------------------------------------------------------
# Ready (RESERVED -> READY)
# ---------------------------------------------------------------------------
@bp.route("/orders/<rid>/ready", methods=["POST"])
@require_roles("StoreAssociate")
def ready_order(rid):
    order = get_or_404(db.orders, rid)
    if order["fulfillment_status"] != "RESERVED" or order["payment_status"] != "AUTHORIZED":
        raise errors.invalid_state("Order is not in a readyable state")
    order["fulfillment_status"] = "READY"
    _touch(order)
    return success(serializers.order(order), 200)


# ---------------------------------------------------------------------------
# Fulfill (READY -> FULFILLED), OCC-guarded
# ---------------------------------------------------------------------------
@bp.route("/orders/<rid>/fulfill", methods=["POST"])
@require_roles("StoreAssociate")
def fulfill_order(rid):
    order = get_or_404(db.orders, rid)
    body = get_body()
    expected = as_int(body, "expected_order_version", required=True)

    # State (priority 6) before OCC (priority 16) per §2.10.
    if order["fulfillment_status"] != "READY" or order["payment_status"] != "AUTHORIZED":
        raise errors.invalid_state("Order is not in a fulfillable state")
    if expected != order["version"]:
        raise errors.ApiError(errors.ERR_STALE_ORDER_VERSION, 412,
                              "expected_order_version is stale")

    customer = db.customers[order["customer_id"]]
    clock_dt = clock.now()
    lines = _lines_for(rid)

    # COMMIT cascade.
    for line in lines:
        row = db.store_inventory[line["store_inventory_id"]]
        commit(row, line["quantity"])
        line["line_status"] = "COMMITTED"
        line["updated_at"] = now_ts()
        line["version"] += 1

    # Final total (applies approved price-match + fulfillment markdown drift).
    final_total, merch_subtotal = pricing.order_total_final(order, customer, clock_dt)
    order["final_total_cents"] = final_total
    order["payment_status"] = "CAPTURED"
    order["fulfillment_status"] = "FULFILLED"

    # Loyalty cascade: +1 point per whole dollar of final merchandise subtotal.
    awarded = merch_subtotal // 100
    order["loyalty_points_awarded"] = awarded
    customer["loyalty_points"] += awarded
    customer["loyalty_tier"] = pricing.loyalty_tier_for_points(customer["loyalty_points"])
    customer["updated_at"] = now_ts()
    customer["version"] += 1

    _touch(order)
    return success(serializers.order(order), 200)


# ---------------------------------------------------------------------------
# Cancel (DRAFT / RESERVED / READY -> CANCELLED)
# ---------------------------------------------------------------------------
@bp.route("/orders/<rid>/cancel", methods=["POST"])
@require_roles("Customer", "StoreAssociate")
def cancel_order(rid):
    order = get_or_404(db.orders, rid)
    # Customer cancelling must own the order (priority 3).
    require_owner(order["customer_id"])

    status = order["fulfillment_status"]
    if status not in ("DRAFT", "RESERVED", "READY"):
        raise errors.invalid_state("Order cannot be cancelled from its current state")

    if status in ("RESERVED", "READY"):
        # RELEASE compensation: reserved_qty returned, on_hand unchanged.
        for line in _lines_for(rid):
            row = db.store_inventory[line["store_inventory_id"]]
            release(row, line["quantity"])
            line["line_status"] = "RELEASED"
            line["updated_at"] = now_ts()
            line["version"] += 1
        order["payment_status"] = "REFUNDED"

    order["fulfillment_status"] = "CANCELLED"
    _touch(order)
    return success(serializers.order(order), 200)
