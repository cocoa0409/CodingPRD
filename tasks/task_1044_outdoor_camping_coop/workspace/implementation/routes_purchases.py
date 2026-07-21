"""Purchase endpoints."""
from flask import Blueprint, request

import store
from errors import err
import core as c

bp = Blueprint("purchases", __name__)


@bp.post("/coop/purchases")
def create_purchase():
    ctx = c.authenticate()
    c.authorize(ctx, {"StoreStaff"})
    body = c.get_body()
    member_id = c.require_str(body, "member_id")
    line_items = body.get("line_items")
    points_redeemed = c.opt_int(body, "points_redeemed", 0)
    if points_redeemed < 0:
        raise err("ERR_VALIDATION", "points_redeemed must be >= 0")
    # structural validation of line items
    if not isinstance(line_items, list) or len(line_items) == 0:
        raise err("ERR_VALIDATION", "line_items must be a non-empty array")
    parsed = []
    for li in line_items:
        if not isinstance(li, dict):
            raise err("ERR_VALIDATION", "each line item must be an object")
        pid = li.get("product_id")
        qty = li.get("quantity")
        unit_price = li.get("unit_price_cents")
        if not isinstance(pid, str) or not pid:
            raise err("ERR_VALIDATION", "line item product_id is required")
        if isinstance(qty, bool) or not isinstance(qty, int):
            raise err("ERR_VALIDATION", "line item quantity must be an integer")
        if isinstance(unit_price, bool) or not isinstance(unit_price, int):
            raise err("ERR_VALIDATION", "line item unit_price_cents must be an integer")
        parsed.append((pid, qty, unit_price))
    # existence
    member = c.lookup("members", member_id)
    for pid, _, _ in parsed:
        c.lookup("products", pid)
    # business constraint: quantity/price sanity
    for pid, qty, unit_price in parsed:
        if qty <= 0 or unit_price < 0:
            raise err("ERR_INVALID_QUANTITY", "line quantity must be > 0 and unit price >= 0")
    # fiscal capacity
    if points_redeemed > c.loyalty_balance(member_id):
        raise err("ERR_INSUFFICIENT_POINTS", "insufficient loyalty points")
    # totals (pinned order)
    subtotal = 0
    tax = 0
    for pid, qty, unit_price in parsed:
        line_subtotal = unit_price * qty
        subtotal += line_subtotal
    for pid, qty, unit_price in parsed:
        product = store.products[pid]
        line_subtotal = unit_price * qty
        tax += c.round_half_up(c.Decimal(line_subtotal) * c.Decimal(str(product["tax_rate"])))
    loyalty_redemption = min(points_redeemed, c.floor_mul(subtotal, c.MAX_REDEEM_PCT))
    total = subtotal + tax - loyalty_redemption
    eligible = subtotal
    points_earned = c.floor_mul(eligible, c.POINTS_PER_CENT)
    purchase = {
        "member_id": member_id,
        "line_items": [
            {"product_id": pid, "quantity": qty, "unit_price_cents": up}
            for pid, qty, up in parsed
        ],
        "points_redeemed": points_redeemed,
        "subtotal_cents": subtotal,
        "tax_cents": tax,
        "loyalty_redemption_cents": loyalty_redemption,
        "total_cents": total,
        "loyalty_points_earned": points_earned,
        "eligible_spend_cents": eligible,
        "status": "COMPLETED",
    }
    store.stamp_new(purchase)
    store.purchases[purchase["id"]] = purchase
    c.append_ledger(member_id, points_earned, "PURCHASE_EARN", purchase["id"])
    if points_redeemed > 0:
        c.append_ledger(member_id, -loyalty_redemption, "PURCHASE_REDEEM", purchase["id"])
    return c.ok(c.ser_purchase(purchase), 201)


@bp.get("/coop/purchases")
def list_purchases():
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff", "CoopAdmin"})
    items = list(store.purchases.values())
    if ctx.role == "Member":
        items = [p for p in items if p["member_id"] == ctx.user_id]
    for key in ("member_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p[key] == val]
    return c.paginate_and_serialize(items, c.ser_purchase)


@bp.get("/coop/purchases/<pid>")
def get_purchase(pid):
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff", "CoopAdmin"})
    p = c.lookup("purchases", pid)
    c.require_owner_member(ctx, p["member_id"])
    return c.ok(c.ser_purchase(p))


@bp.post("/coop/purchases/<pid>/refund")
def refund(pid):
    ctx = c.authenticate()
    c.authorize(ctx, {"StoreStaff"})
    p = c.lookup("purchases", pid)
    if p["status"] != "COMPLETED":
        raise err("ERR_INVALID_STATE", "purchase is not COMPLETED")
    p["status"] = "REFUNDED"
    store.touch(p)
    c.append_ledger(p["member_id"], -p["loyalty_points_earned"], "PURCHASE_REFUND_REVERSAL", p["id"])
    if p["points_redeemed"] > 0:
        c.append_ledger(p["member_id"], p["loyalty_redemption_cents"], "PURCHASE_REFUND_REVERSAL", p["id"])
    return c.ok(c.ser_purchase(p))
