"""Order, OrderItem, redemption, payment-flow, and credit-entries endpoints."""

from flask import Blueprint, request

import errors as E
import middleware as M
import response as R
import services as S
from db import store, new_id, stamp_created, touch, clock_iso

bp = Blueprint("orders", __name__)

READ_ROLES = S.ALL_ROLES
BUYER_ONLY = {"SalonBuyer"}
ADMIN_ONLY = {"DistributionAdmin"}


def _parse_items_input(data):
    """Validate the items array schema (pipeline step 2)."""
    items = data.get("items")
    if items is None:
        raise E.invalid_request("Missing required field: items")
    if not isinstance(items, list):
        raise E.invalid_request("Field items must be an array")
    parsed = []
    for el in items:
        if not isinstance(el, dict):
            raise E.invalid_request("Each item must be an object")
        M.no_unknown(el, {"product_id", "quantity"})
        pid = M.req_string(el, "product_id")
        qty = M.req_pos_int(el, "quantity")
        parsed.append((pid, qty))
    return parsed


def _load_buyer_order(ctx, oid):
    order = S.get_order(oid)
    S.buyer_scope(ctx, order["salon_account_id"])
    return order


# ---------------------------------------------------------------------------
# Order CRUD
# ---------------------------------------------------------------------------
@bp.post("/api/orders")
def create_order():
    ctx = M.require_auth()
    data = M.body()
    M.no_unknown(data, {"salon_account_id", "items"})
    salon_id = M.req_string(data, "salon_account_id")
    items_in = _parse_items_input(data)
    M.require_role(ctx, BUYER_ONLY)
    S.buyer_scope(ctx, salon_id)
    salon = S.get_salon(salon_id)
    products = []
    for pid, _qty in items_in:
        products.append(S.get_product(pid))
    for p in products:
        if p["lifecycle_status"] not in ("ACTIVE", "LIQUIDATION"):
            raise E.invalid_product_state("Only ACTIVE or LIQUIDATION products can be ordered")
    if salon["status"] != "ACTIVE":
        raise E.account_not_active()
    for p in products:
        S.check_territory(p, salon)
    order = {
        "id": new_id(),
        "salon_account_id": salon["id"],
        "fulfillment_status": "DRAFT",
        "payment_status": "UNPAID",
        "merchandise_total_cents": 0,
        "credit_applied_cents": 0,
        "net_merch_cents": 0,
        "shipping_total_cents": 0,
        "grand_total_cents": 0,
        "promo_applied_code": None,
        "submitted_at": None,
        "delivered_at": None,
    }
    stamp_created(order)
    store.orders[order["id"]] = order
    for p, (_pid, qty) in zip(products, items_in):
        unit, snapshot = S.price_line(p, salon)
        S.add_order_item(order, p, qty, unit, snapshot, False)
    S.recompute_order_totals(order)
    return R.success_object(S.pub(order), 201)


@bp.get("/api/orders")
def list_orders():
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    items = list(store.orders.values())
    salon_id = request.args.get("salon_account_id")
    if ctx.role == "SalonBuyer":
        if salon_id is not None and salon_id != ctx.user_id:
            raise E.forbidden()
        items = [o for o in items if o["salon_account_id"] == ctx.user_id]
    elif salon_id is not None:
        items = [o for o in items if o["salon_account_id"] == salon_id]
    fs = request.args.get("fulfillment_status")
    if fs is not None:
        items = [o for o in items if o["fulfillment_status"] == fs]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.pub_list(page), limit, offset, total)


@bp.get("/api/orders/<oid>")
def get_order(oid):
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    order = S.get_order(oid)
    S.read_scope_order(ctx, order)
    return R.success_object(S.pub(order))


# ---------------------------------------------------------------------------
# OrderItem add / remove / read
# ---------------------------------------------------------------------------
@bp.post("/api/orders/<oid>/items")
def add_item(oid):
    ctx = M.require_auth()
    data = M.body()
    M.no_unknown(data, {"product_id", "quantity", "expected_order_version"})
    product_id = M.req_string(data, "product_id")
    quantity = M.req_pos_int(data, "quantity")
    expected = M.req_int(data, "expected_order_version")
    M.require_role(ctx, BUYER_ONLY)
    order = _load_buyer_order(ctx, oid)
    product = S.get_product(product_id)
    if order["fulfillment_status"] != "DRAFT":
        raise E.invalid_order_state("Items can be added only to a DRAFT order")
    if expected != order["version"]:
        raise E.stale_version()
    salon = store.salons.get(order["salon_account_id"])
    if product["lifecycle_status"] not in ("ACTIVE", "LIQUIDATION"):
        raise E.invalid_product_state("Only ACTIVE or LIQUIDATION products can be ordered")
    S.check_territory(product, salon)
    unit, snapshot = S.price_line(product, salon)
    item = S.add_order_item(order, product, quantity, unit, snapshot, False)
    S.recompute_order_totals(order)
    touch(order)
    return R.success_object(S.pub(item), 201)


@bp.delete("/api/orders/<oid>/items/<item_id>")
def remove_item(oid, item_id):
    ctx = M.require_auth()
    M.require_role(ctx, BUYER_ONLY)
    order = _load_buyer_order(ctx, oid)
    item = store.order_items.get(item_id)
    if item is None or item["order_id"] != order["id"]:
        raise E.order_item_not_found()
    if order["fulfillment_status"] != "DRAFT":
        raise E.invalid_order_state("Items can be removed only from a DRAFT order")
    if item["is_promotional"]:
        raise E.invalid_order_state("Promotional lines of an APPLIED redemption are not removable")
    del store.order_items[item["id"]]
    S.recompute_order_totals(order)
    touch(order)
    return R.no_content()


@bp.get("/api/order-items")
def list_order_items():
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    items = list(store.order_items.values())
    order_id = request.args.get("order_id")
    product_id = request.args.get("product_id")
    if ctx.role == "SalonBuyer":
        own_orders = {o["id"] for o in store.orders.values()
                      if o["salon_account_id"] == ctx.user_id}
        if order_id is not None and order_id not in own_orders:
            if order_id in store.orders:
                raise E.forbidden()
            items = []
        else:
            items = [i for i in items if i["order_id"] in own_orders]
    if order_id is not None:
        items = [i for i in items if i["order_id"] == order_id]
    if product_id is not None:
        items = [i for i in items if i["product_id"] == product_id]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.pub_list(page), limit, offset, total)


@bp.get("/api/order-items/<iid>")
def get_order_item(iid):
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    item = store.order_items.get(iid)
    if item is None:
        raise E.order_item_not_found()
    order = store.orders.get(item["order_id"])
    if order is not None:
        S.read_scope_order(ctx, order)
    return R.success_object(S.pub(item))


# ---------------------------------------------------------------------------
# Credit redemption (PRD 3.5)
# ---------------------------------------------------------------------------
@bp.post("/api/orders/<oid>/redeem-credits")
def redeem_credits(oid):
    ctx = M.require_auth()
    data = M.body()
    M.no_unknown(data, {"points"})
    points = M.req_pos_int(data, "points")
    M.require_role(ctx, BUYER_ONLY)
    order = _load_buyer_order(ctx, oid)
    if order["fulfillment_status"] != "DRAFT":
        raise E.invalid_order_state("Credits can be redeemed only on a DRAFT order")
    salon = store.salons.get(order["salon_account_id"])
    # pinned check order: (1) balance, (2) cap
    if points > S.redeemable_points(salon):
        raise E.insufficient_credit_balance()
    requested_cents = points * S.POINT_VALUE_CENTS
    cap_cents = order["merchandise_total_cents"] // 2
    if requested_cents > cap_cents:
        raise E.credit_redemption_exceeds_cap()
    S.redeem_credits(salon, order, points)
    order["credit_applied_cents"] += requested_cents
    S.recompute_order_totals(order)
    touch(order)
    return R.success_object(S.pub(order))


# ---------------------------------------------------------------------------
# Promotion redemption (PRD 3.5 waterfall)
# ---------------------------------------------------------------------------
@bp.post("/api/orders/<oid>/redeem-promotion")
def redeem_promotion(oid):
    ctx = M.require_auth()
    data = M.body()
    M.no_unknown(data, {"code"})
    code = M.req_string(data, "code")
    M.require_role(ctx, BUYER_ONLY)
    order = _load_buyer_order(ctx, oid)
    promo = None
    for p in store.promotions.values():
        if p["code"] == code:
            promo = p
            break
    if promo is None:
        raise E.promotion_not_found("Unknown promotion code")
    if order["fulfillment_status"] != "DRAFT":
        raise E.invalid_order_state("Promotions can be redeemed only on a DRAFT order")
    if promo["status"] != "ACTIVE":
        raise E.invalid_promotion_state("Promotion is not ACTIVE")
    now = store.clock
    if not (S.parse_dt(promo["starts_at"]) <= now < S.parse_dt(promo["ends_at"])):
        raise E.promotion_not_active()
    salon = store.salons.get(order["salon_account_id"])
    if salon["tier"] not in promo["eligible_tiers"]:
        raise E.promotion_tier_ineligible()
    for r in store.redemptions.values():
        if r["promotion_id"] == promo["id"] and r["order_id"] == order["id"] and r["status"] == "APPLIED":
            raise E.promotion_already_applied()
    items = S.items_of_order(order["id"])
    if promo["promo_type"] == "BUNDLE":
        have = sum(i["quantity"] for i in items
                   if not i["is_promotional"] and i["product_id"] == promo["required_product_id"])
        if have < promo["required_qty"]:
            raise E.bundle_requirement_not_met()
        units = promo["free_qty"]
        grant_product_id = promo["free_product_id"]
    else:
        units = promo["sample_units_per_redemption"]
        grant_product_id = promo["sample_product_id"]
    if promo["remaining_budget_units"] is None or promo["remaining_budget_units"] < units:
        raise E.promotion_budget_exhausted()
    salon_used = sum(r["units_consumed"] for r in store.redemptions.values()
                     if r["promotion_id"] == promo["id"]
                     and r["salon_account_id"] == salon["id"] and r["status"] == "APPLIED")
    if salon_used + units > promo["per_salon_cap"]:
        raise E.per_salon_cap_exceeded()
    grant_product = store.products.get(grant_product_id)
    if grant_product is None:
        raise E.product_not_found()
    S.add_order_item(order, grant_product, units, 0, f"PROMOTION:{code}", True)
    redemption = {
        "id": new_id(),
        "promotion_id": promo["id"],
        "order_id": order["id"],
        "salon_account_id": salon["id"],
        "units_consumed": units,
        "status": "APPLIED",
        "reversal_reason": None,
    }
    stamp_created(redemption)
    store.redemptions[redemption["id"]] = redemption
    promo["remaining_budget_units"] -= units
    if promo["remaining_budget_units"] == 0:
        promo["status"] = "ENDED"
    touch(promo)
    order["promo_applied_code"] = code
    S.recompute_order_totals(order)
    touch(order)
    return R.success_object(S.pub(order))


# ---------------------------------------------------------------------------
# Order state flow (PRD 3.6)
# ---------------------------------------------------------------------------
@bp.post("/api/orders/<oid>/submit")
def submit_order(oid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, BUYER_ONLY)
    order = _load_buyer_order(ctx, oid)
    if order["fulfillment_status"] != "DRAFT":
        raise E.invalid_order_state("Only a DRAFT order can be submitted")
    items = S.items_of_order(order["id"])
    if not any(not i["is_promotional"] for i in items):
        raise E.invalid_order_state("Order must contain at least one non-promotional item")
    salon = store.salons.get(order["salon_account_id"])
    if salon is None or salon["status"] != "ACTIVE":
        raise E.account_not_active()
    if not S.backbar_quota_ok(salon, order):
        raise E.backbar_quota_exceeded()
    for i in items:
        product = store.products.get(i["product_id"])
        if product is not None:
            S.check_territory(product, salon)
    # credit revalidation, pinned order: balance first, then cap
    if order["credit_applied_cents"] > 0:
        redeemed_points = order["credit_applied_cents"] // S.POINT_VALUE_CENTS
        already_consumed = redeemed_points
        if redeemed_points > S.redeemable_points(salon) + already_consumed:
            raise E.insufficient_credit_balance()
        cap_cents = order["merchandise_total_cents"] // 2
        if order["credit_applied_cents"] > cap_cents:
            raise E.credit_redemption_exceeds_cap()
    order["payment_status"] = "AUTHORIZED"
    order["fulfillment_status"] = "SUBMITTED"
    order["submitted_at"] = clock_iso()
    S.post_provisional_accrual(order, salon)
    touch(order)
    return R.success_object(S.pub(order))


@bp.post("/api/orders/<oid>/cancel")
def cancel_order(oid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, BUYER_ONLY)
    order = _load_buyer_order(ctx, oid)
    if order["fulfillment_status"] not in ("DRAFT", "SUBMITTED"):
        raise E.invalid_order_state("Only a DRAFT or SUBMITTED order can be cancelled by the buyer")
    S.cancel_order_with_compensation(order, "ORDER_CANCELLED")
    return R.success_object(S.pub(order))


@bp.post("/api/orders/<oid>/approve")
def approve_order(oid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, ADMIN_ONLY)
    order = S.get_order(oid)
    if order["fulfillment_status"] != "SUBMITTED":
        raise E.invalid_order_state("Only a SUBMITTED order can be approved")
    salon = store.salons.get(order["salon_account_id"])
    if salon is None or salon["status"] != "ACTIVE":
        raise E.account_not_active()
    order["fulfillment_status"] = "APPROVED"
    order["payment_status"] = "CAPTURED"
    touch(order)
    return R.success_object(S.pub(order))


@bp.post("/api/orders/<oid>/reject")
def reject_order(oid):
    ctx = M.require_auth()
    data = M.body()
    M.no_unknown(data, {"reason"})
    M.req_string(data, "reason")
    M.require_role(ctx, ADMIN_ONLY)
    order = S.get_order(oid)
    if order["fulfillment_status"] != "SUBMITTED":
        raise E.invalid_order_state("Only a SUBMITTED order can be rejected")
    S.reject_order_with_compensation(order)
    return R.success_object(S.pub(order))


# ---------------------------------------------------------------------------
# Credit entries tied to an order
# ---------------------------------------------------------------------------
@bp.get("/api/orders/<oid>/credit-entries")
def order_credit_entries(oid):
    ctx = M.require_auth()
    M.require_role(ctx, {"DistributionAdmin", "ComplianceOfficer", "SalonBuyer"})
    order = S.get_order(oid)
    S.read_scope_order(ctx, order)
    items = [e for e in S.credit_entries_of_salon(order["salon_account_id"])
             if e["order_id"] == order["id"]]
    page, limit, offset, total = M.paginate(items, key=S.ledger_sort_key)
    return R.success_list(S.pub_list(page), limit, offset, total)
