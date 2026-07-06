"""Pricing, calorie, redemption, points-earn and clawback calculations (PRD §3.4-3.8, §1.3)."""
from decimal import Decimal, ROUND_HALF_UP

from db import db

# delivery_fee constants (§1.3)
DELIVERY_BASE_CENTS = 399
LOCKER_FEE_CENTS = 99
DEFAULT_SURCHARGE_BPS = 0
SURCHARGE_BPS_BY_STATE = {"CA": 800, "NY": 875, "TX": 0}

# redemption (§1.3)
MIN_REDEEM_BLOCK = 100
BLOCK_VALUE_CENTS = 100

# points_earned (§1.3)
CENTS_PER_POINT = 10


def round_half_up(value):
    """Round a numeric value half-up to the nearest integer."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------- line-level ----------
def compute_line(menu_item, modifiers, quantity):
    """Returns (line_total_cents, line_calories, effective_allergen_tags)."""
    per_unit_cents = menu_item["base_price_cents"] + sum(
        m["price_delta_cents"] for m in modifiers
    )
    line_total_cents = per_unit_cents * quantity

    per_unit_cal = menu_item["base_calories"] + sum(m["calorie_delta"] for m in modifiers)
    line_calories = max(0, per_unit_cal) * quantity

    tags = set(menu_item.get("allergen_tags") or [])
    for m in modifiers:
        tags.update(m.get("adds_allergen_tags") or [])
    return line_total_cents, line_calories, sorted(tags)


def recompute_order_lines_totals(order):
    """Recompute Order.subtotal_cents and total_calories from its lines."""
    subtotal = 0
    cals = 0
    for line in db.order_lines.values():
        if line["order_id"] == order["id"]:
            subtotal += line["line_total_cents"]
            cals += line["line_calories"]
    order["subtotal_cents"] = subtotal
    order["total_calories"] = cals


# ---------- placement pricing ----------
def delivery_fee(channel, state_code, subtotal_cents, sub_active_free_delivery):
    if channel == "COUNTER":
        raw_fee = 0
    elif channel == "LOCKER":
        raw_fee = LOCKER_FEE_CENTS
    else:  # DELIVERY
        band = SURCHARGE_BPS_BY_STATE.get(state_code, DEFAULT_SURCHARGE_BPS)
        surcharge = round_half_up(subtotal_cents * band / 10000)
        raw_fee = DELIVERY_BASE_CENTS + surcharge
    # waiver applies ONLY to DELIVERY, never to the LOCKER fee
    if channel == "DELIVERY" and sub_active_free_delivery:
        return 0
    return raw_fee


def redemption_value(points_redeemed, subtotal_cents):
    usable_blocks = points_redeemed // MIN_REDEEM_BLOCK
    discount = usable_blocks * BLOCK_VALUE_CENTS
    return min(discount, subtotal_cents)


def order_total(subtotal_cents, discount_cents, delivery_fee_cents, wallet_credit_cents):
    """Pinned waterfall. Returns (wallet_applied_cents, total_cents)."""
    residual = subtotal_cents - discount_cents + delivery_fee_cents
    wallet_applied = min(wallet_credit_cents, residual)
    total = max(0, residual - wallet_applied)
    return wallet_applied, total


def points_earned(subtotal_cents, discount_cents, sub_active, multiplier_bps):
    eligible = max(0, subtotal_cents - discount_cents)
    base_points = eligible // CENTS_PER_POINT
    if sub_active:
        return (base_points * multiplier_bps) // 10000
    return base_points


def points_clawback(order, refund_amount_cents, prior_clawback):
    """Proportional clawback on a COMPLETED order (§1.3 points_clawback)."""
    if order["order_status"] != "COMPLETED" or order["points_earned"] == 0:
        return 0
    total = order["total_cents"]
    if total <= 0:
        return 0
    share = Decimal(refund_amount_cents) / Decimal(total)
    raw = round_half_up(Decimal(order["points_earned"]) * share)
    cap = order["points_earned"] - prior_clawback
    return min(raw, cap)
