"""Order endpoints — create, pay, ship, deliver, complete, cancel."""
from flask import Blueprint, request
from auth import get_auth, require_role, require_shop_owner, require_buyer_owner
from db import store, stamp_common, touch, now
from envelope import success
from errors import (
    raise_err, ERR_VALIDATION, ERR_ORDER_NOT_FOUND, ERR_SHOP_NOT_FOUND,
    ERR_LISTING_NOT_FOUND, ERR_PERSONALIZATION_TOO_LONG, ERR_LISTING_NOT_PURCHASABLE,
    ERR_SHOP_ON_VACATION, ERR_PERSONALIZATION_REQUIRED, ERR_INVALID_STATE,
    ERR_PRODUCTION_CAPACITY_EXCEEDED, ERR_INSUFFICIENT_INVENTORY,
)
from helpers import get_json_body, require_field, opt_field, parse_pagination, paginate, sort_by_created
from serializers import order_view
from services import (
    find_shop, find_variation, pay_cascade_check_sold_out, cancel_cascade_restore_listing,
    update_material_status, production_windows_overlap_count,
)
from calculations import compute_order_shipping, compute_order_fees, compute_ship_by

bp = Blueprint("orders", __name__)


def _require_order(oid):
    o = store.orders.get(oid)
    if o is None:
        raise_err(ERR_ORDER_NOT_FOUND, "not found")
    return o


@bp.route("/seller/orders", methods=["POST"])
def create():
    user_id, role = get_auth()
    require_role(role, {"Buyer"})
    body = get_json_body()
    shop_id = require_field(body, "shop_id", str)
    listing_id = require_field(body, "listing_id", str)
    quantity = require_field(body, "quantity", int)

    # Existence (left-to-right).
    shop = find_shop(shop_id)
    if shop is None:
        raise_err(ERR_SHOP_NOT_FOUND, "shop not found")
    listing = store.listings.get(listing_id)
    if listing is None:
        raise_err(ERR_LISTING_NOT_FOUND, "listing not found")

    # Structural validation (post existence).
    if quantity < 1:
        raise_err(ERR_VALIDATION, "quantity must be >= 1")

    variation_id = opt_field(body, "variation_id", str, None)
    variation = None
    if variation_id is not None:
        variation = find_variation(listing, variation_id)
        if variation is None:
            raise_err(ERR_VALIDATION, "unknown variation_id")

    personalization_note = opt_field(body, "personalization_note", str, None)

    # 400: personalization_note length <= limit
    if personalization_note is not None:
        if len(personalization_note) > listing["personalization_char_limit"]:
            raise_err(ERR_PERSONALIZATION_TOO_LONG, "personalization_note too long")

    # 409: listing must be ACTIVE (purchasable)
    if listing["status"] != "ACTIVE":
        raise_err(ERR_LISTING_NOT_PURCHASABLE, "listing not ACTIVE")

    # 422: shop must not be on VACATION/SUSPENDED/CLOSED
    if shop["status"] in ("VACATION", "SUSPENDED", "CLOSED"):
        raise_err(ERR_SHOP_ON_VACATION, "shop not accepting orders")

    # 422: personalization required
    if listing["personalization_required"]:
        if personalization_note is None or personalization_note == "":
            raise_err(ERR_PERSONALIZATION_REQUIRED, "personalization required")

    sp = store.shipping_profiles.get(listing["shipping_profile_id"])
    if sp is None:
        # Data integrity: shouldn't happen if listing created legally.
        raise_err(ERR_VALIDATION, "listing has no shipping profile")

    item_subtotal, shipping, total = compute_order_shipping(listing, variation, quantity, sp)

    rec = {
        "shop_id": shop_id,
        "listing_id": listing_id,
        "variation_id": variation_id,
        "payout_id": None,
        "buyer_id": user_id,
        "quantity": quantity,
        "personalization_note": personalization_note,
        "item_subtotal_cents": item_subtotal,
        "shipping_cents": shipping,
        "order_total_cents": total,
        "order_fee_cents": 0,
        "order_net_cents": 0,
        "refunded_cents": 0,
        "payment_status": "UNPAID",
        "fulfillment_status": "NOT_STARTED",
        "has_open_case": False,
        "paid_at": None,
        "ship_by_date": None,
        "shipped_at": None,
        "cancel_reason": None,
    }
    stamp_common(rec)
    store.orders[rec["id"]] = rec
    return success(order_view(rec), status=201)


@bp.route("/seller/orders/<oid>", methods=["GET"])
def fetch(oid):
    user_id, role = get_auth()
    require_role(role, {"Seller", "PlatformAdmin", "Buyer"})
    o = _require_order(oid)
    return success(order_view(o))


@bp.route("/seller/orders", methods=["GET"])
def list_():
    user_id, role = get_auth()
    require_role(role, {"Seller", "PlatformAdmin", "Buyer"})
    limit, offset = parse_pagination()
    args = request.args
    shop_id = args.get("shop_id")
    listing_id = args.get("listing_id")
    payout_id = args.get("payout_id")
    buyer_id = args.get("buyer_id")
    pmt = args.get("payment_status")
    ful = args.get("fulfillment_status")

    items = list(store.orders.values())
    if shop_id is not None:
        items = [x for x in items if x["shop_id"] == shop_id]
    if listing_id is not None:
        items = [x for x in items if x["listing_id"] == listing_id]
    if payout_id is not None:
        items = [x for x in items if x.get("payout_id") == payout_id]
    if buyer_id is not None:
        items = [x for x in items if x["buyer_id"] == buyer_id]
    if pmt is not None:
        items = [x for x in items if x["payment_status"] == pmt]
    if ful is not None:
        items = [x for x in items if x["fulfillment_status"] == ful]
    if role == "Seller":
        items = [x for x in items if x["shop_id"] == user_id]
    elif role == "Buyer":
        items = [x for x in items if x["buyer_id"] == user_id]
    items = sort_by_created(items)
    page, pmeta = paginate(items, limit, offset)
    return success([order_view(x) for x in page], response_type="array", pagination=pmeta)


@bp.route("/seller/orders/<oid>/pay", methods=["POST"])
def pay(oid):
    user_id, role = get_auth()
    require_role(role, {"Buyer"})
    o = _require_order(oid)
    require_buyer_owner(user_id, role, o["buyer_id"])

    # State check first per §3.5 (payment defined only from UNPAID).
    if o["payment_status"] != "UNPAID":
        raise_err(ERR_INVALID_STATE, "order not UNPAID")

    shop = store.shops[o["shop_id"]]
    listing = store.listings[o["listing_id"]]

    # Shop must not be closed to business.
    if shop["status"] in ("VACATION", "SUSPENDED", "CLOSED"):
        raise_err(ERR_SHOP_ON_VACATION, "shop not accepting payments")

    # Compute effective fields we need for capacity check.
    paid_at = now()
    sp = store.shipping_profiles[listing["shipping_profile_id"]]
    ship_by = compute_ship_by(paid_at, listing, sp)

    if listing["fulfillment_type"] == "MADE_TO_ORDER":
        # Capacity check: count existing overlapping production windows.
        existing = production_windows_overlap_count(o["shop_id"], paid_at, ship_by)
        # This order would be a NEW window; comparison is "existing count + this one".
        # PRD: "counting the shop's orders whose production window would overlap this
        # order's window, that count must remain within the shop's max_concurrent_production".
        # Interpretation: the count of overlapping windows including this one must be
        # <= max_concurrent_production.
        if existing + 1 > shop["max_concurrent_production"]:
            raise_err(ERR_PRODUCTION_CAPACITY_EXCEEDED, "capacity exceeded")

    # Inventory check.
    variation = find_variation(listing, o.get("variation_id"))
    qty = o["quantity"]
    if listing["fulfillment_type"] == "READY_TO_SHIP":
        if variation is not None:
            if variation["stock_qty"] < qty:
                raise_err(ERR_INSUFFICIENT_INVENTORY, "variation stock insufficient")
        else:
            if listing["quantity"] < qty:
                raise_err(ERR_INSUFFICIENT_INVENTORY, "listing stock insufficient")
    else:  # MADE_TO_ORDER
        mid = listing.get("primary_material_id")
        if mid:
            mat = store.materials.get(mid)
            if mat is None:
                raise_err(ERR_INSUFFICIENT_INVENTORY, "material missing")
            needed = listing["material_qty_per_unit"] * qty
            if mat["stock_qty"] < needed:
                raise_err(ERR_INSUFFICIENT_INVENTORY, "material stock insufficient")

    # === All preconditions satisfied; commit. ===
    order_fee, order_net = compute_order_fees(o["order_total_cents"])
    o["order_fee_cents"] = order_fee
    o["order_net_cents"] = order_net
    o["payment_status"] = "PAID"
    o["paid_at"] = paid_at
    o["ship_by_date"] = ship_by
    if listing["fulfillment_type"] == "MADE_TO_ORDER":
        o["fulfillment_status"] = "IN_PRODUCTION"

    # Inventory decrement.
    if listing["fulfillment_type"] == "READY_TO_SHIP":
        if variation is not None:
            variation["stock_qty"] -= qty
        listing["quantity"] -= qty
        touch(listing)
    else:
        mid = listing.get("primary_material_id")
        if mid:
            mat = store.materials[mid]
            needed = listing["material_qty_per_unit"] * qty
            mat["stock_qty"] -= needed
            update_material_status(mat)
            touch(mat)

    # Cascade to SOLD_OUT if applicable.
    pay_cascade_check_sold_out(listing, variation)

    # Shop ledger updates.
    shop["pending_balance_cents"] += order_net
    shop["lifetime_gross_cents"] += o["order_total_cents"]
    touch(shop)

    touch(o)
    return success(order_view(o))


@bp.route("/seller/orders/<oid>/ship", methods=["POST"])
def ship(oid):
    user_id, role = get_auth()
    require_role(role, {"Seller"})
    o = _require_order(oid)
    require_shop_owner(user_id, role, o["shop_id"])
    if o["payment_status"] != "PAID":
        raise_err(ERR_INVALID_STATE, "order not PAID")
    if o["fulfillment_status"] not in ("NOT_STARTED", "IN_PRODUCTION"):
        raise_err(ERR_INVALID_STATE, "wrong fulfillment state")
    o["fulfillment_status"] = "SHIPPED"
    o["shipped_at"] = now()
    touch(o)
    return success(order_view(o))


@bp.route("/seller/orders/<oid>/deliver", methods=["POST"])
def deliver(oid):
    user_id, role = get_auth()
    require_role(role, {"Seller"})
    o = _require_order(oid)
    require_shop_owner(user_id, role, o["shop_id"])
    if o["fulfillment_status"] != "SHIPPED":
        raise_err(ERR_INVALID_STATE, "order not SHIPPED")
    o["fulfillment_status"] = "DELIVERED"
    touch(o)
    return success(order_view(o))


@bp.route("/seller/orders/<oid>/complete", methods=["POST"])
def complete(oid):
    user_id, role = get_auth()
    require_role(role, {"Buyer"})
    o = _require_order(oid)
    require_buyer_owner(user_id, role, o["buyer_id"])
    if o["fulfillment_status"] != "DELIVERED":
        raise_err(ERR_INVALID_STATE, "order not DELIVERED")
    o["fulfillment_status"] = "COMPLETED"
    # Move net from pending -> available.
    shop = store.shops[o["shop_id"]]
    net = o["order_net_cents"]
    shop["pending_balance_cents"] -= net
    shop["available_balance_cents"] += net
    touch(shop)
    touch(o)
    return success(order_view(o))


@bp.route("/seller/orders/<oid>/cancel", methods=["POST"])
def cancel(oid):
    user_id, role = get_auth()
    require_role(role, {"Seller"})
    o = _require_order(oid)
    require_shop_owner(user_id, role, o["shop_id"])
    if o["fulfillment_status"] not in ("NOT_STARTED", "IN_PRODUCTION"):
        raise_err(ERR_INVALID_STATE, "order cannot be cancelled from this state")

    body = get_json_body()
    cancel_reason = opt_field(body, "cancel_reason", str, None)

    was_paid = (o["payment_status"] == "PAID")

    o["fulfillment_status"] = "CANCELLED"
    o["cancel_reason"] = cancel_reason

    listing = store.listings.get(o["listing_id"])
    variation = find_variation(listing, o.get("variation_id")) if listing else None
    qty = o["quantity"]

    if was_paid:
        # Restore inventory / material.
        if listing is not None:
            if listing["fulfillment_type"] == "READY_TO_SHIP":
                if variation is not None:
                    variation["stock_qty"] += qty
                listing["quantity"] += qty
                touch(listing)
            else:  # MADE_TO_ORDER
                mid = listing.get("primary_material_id")
                if mid:
                    mat = store.materials.get(mid)
                    if mat is not None:
                        needed = listing["material_qty_per_unit"] * qty
                        mat["stock_qty"] += needed
                        update_material_status(mat)
                        touch(mat)

            # Free SOLD_OUT listings that are sellable again.
            cancel_cascade_restore_listing(listing)
            # For material-freed cascade: also check other MADE_TO_ORDER listings.
            if listing["fulfillment_type"] == "MADE_TO_ORDER":
                mid = listing.get("primary_material_id")
                if mid:
                    from services import cascade_material_freed
                    mat = store.materials.get(mid)
                    if mat is not None:
                        cascade_material_freed(mat)

        # Ledger: reverse pending credit.
        shop = store.shops[o["shop_id"]]
        shop["pending_balance_cents"] -= o["order_net_cents"]
        touch(shop)

        # Payment axis.
        o["payment_status"] = "REFUNDED"
        o["refunded_cents"] = o["order_total_cents"]

    touch(o)
    return success(order_view(o))
