from datetime import datetime, timezone, timedelta
from decimal import Decimal
from store import store
from common import round_half_up, sort_created, serialize

POINT_VALUE_CENTS = 1
SILVER_CENTS = 50000
GOLD_CENTS = 150000


# --------------------------------------------------------------------------
# Inventory
# --------------------------------------------------------------------------
def product_lot(product_id):
    """Earliest-created InventoryLot for a product, or None."""
    lots = [l for l in store.inventory_lots.values() if l["product_id"] == product_id]
    if not lots:
        return None
    return sort_created(lots)[0]


def lot_available(lot):
    return lot["on_hand_yards"] - lot["reserved_yards"]


# --------------------------------------------------------------------------
# Pricing
# --------------------------------------------------------------------------
def order_lines_for(order_id, statuses=None):
    lines = [l for l in store.order_lines.values() if l["order_id"] == order_id]
    if statuses is not None:
        lines = [l for l in lines if l["status"] in statuses]
    return sort_created(lines)


def compute_line_subtotal(line, variant):
    product = store.products.get(line["product_id"])
    if product is None:
        return 0
    if variant == "provisional":
        qty = line["requested_yards"]
    else:
        if product["sell_mode"] == "BY_YARD":
            qty = line["actual_cut_yards"]
        else:
            qty = line["requested_yards"]
    if qty is None:
        qty = 0
    raw = Decimal(str(product["unit_price_cents"])) * Decimal(str(qty))
    return round_half_up(raw)


def coupon_discount(order, subtotal, clearance_subtotal):
    coupon_ids = order.get("_applied_coupons", [])
    coupons = [store.coupons[cid] for cid in coupon_ids if cid in store.coupons]
    coupons.sort(key=lambda c: (c["priority"], c["_seq"]))
    running = subtotal
    discount = 0
    for c in coupons:
        if running < c["min_basket_cents"]:
            continue
        if c["discount_type"] == "PERCENT":
            base = running - clearance_subtotal if c["excludes_clearance"] else running
            if base < 0:
                base = 0
            d = round_half_up(Decimal(str(base)) * Decimal(str(c["value"])))
        else:  # FIXED
            d = min(c["value"], running)
        discount += d
        running -= d
    return discount


def price_order(order, variant, statuses=("RESERVED", "FULFILLED")):
    """Compute total for an order under the given pricing variant.
    Also refreshes line_subtotal_cents on qualifying lines."""
    lines = order_lines_for(order["id"], statuses=statuses)
    subtotal = 0
    clearance_subtotal = 0
    for line in lines:
        ls = compute_line_subtotal(line, variant)
        line["line_subtotal_cents"] = ls
        subtotal += ls
        product = store.products.get(line["product_id"])
        if product is not None and product.get("is_clearance"):
            clearance_subtotal += ls
    discount = coupon_discount(order, subtotal, clearance_subtotal)
    redeem = order.get("points_redeemed_on_order", 0) * POINT_VALUE_CENTS
    total = max(0, subtotal - discount - redeem)
    return total


def order_subtotal(order, variant="provisional"):
    lines = order_lines_for(order["id"], statuses=("RESERVED", "FULFILLED"))
    subtotal = 0
    for line in lines:
        subtotal += compute_line_subtotal(line, variant)
    return subtotal


# --------------------------------------------------------------------------
# Loyalty
# --------------------------------------------------------------------------
def tier_of(spend):
    if spend >= GOLD_CENTS:
        return "GOLD"
    if spend >= SILVER_CENTS:
        return "SILVER"
    return "BASIC"


def loyalty_by_customer(customer_id):
    for acct in store.loyalty_accounts.values():
        if acct["customer_id"] == customer_id:
            return acct
    return None


def loyalty_view(acct):
    view = serialize(acct)
    earned = acct["points_earned"]
    redeemed = acct["points_redeemed"]
    view["points_balance"] = earned - redeemed
    spend_ytd = acct["spend_ytd_cents"]
    now = store.clock.now
    jan1 = datetime(now.year, 1, 1, tzinfo=timezone.utc)
    days_elapsed = max(1, (now.date() - jan1.date()).days + 1)
    projected = spend_ytd / days_elapsed * 365
    view["tier_forward"] = tier_of(projected)
    # chronological: rolling 365-day actual finalized spend
    window_start = now - timedelta(days=365)
    rolling = 0
    for order in store.orders.values():
        if (order["customer_id"] == acct["customer_id"]
                and order["fulfillment_status"] == "PICKED_UP"):
            pu = order.get("_picked_up_at")
            if pu is not None and pu >= window_start:
                rolling += order.get("final_total_cents") or 0
    view["tier_chronological"] = tier_of(rolling)
    return view


# --------------------------------------------------------------------------
# Serialization for entities with computed fields
# --------------------------------------------------------------------------
def lot_view(lot):
    v = serialize(lot)
    v["available_yards"] = lot_available(lot)
    return v


def registration_view(reg):
    v = serialize(reg)
    if reg["status"] == "WAITLISTED":
        peers = [r for r in store.registrations.values()
                 if r["session_id"] == reg["session_id"] and r["status"] == "WAITLISTED"]
        peers = sort_created(peers)
        rank = None
        for i, r in enumerate(peers, start=1):
            if r["id"] == reg["id"]:
                rank = i
                break
        v["waitlist_rank"] = rank
    else:
        v["waitlist_rank"] = None
    return v
