"""Calculation rules: order_total, loyalty accrual, renewal charge, churn, bulk quote."""
from helpers import round_half_up

# --- constants (from scaffold §1.3) ---
PERISHABLE_HANDLING_CENTS = 450
PERISHABLE_SHIP_MULT = 1.5
LOYALTY_MAX_REDEEM_PCT = 0.30
ZONE_BASE = {"Z1": 500, "Z2": 800, "Z3": 1200, "Z4": 1800}

EARN_RATE_PER_CENT = 0.015

TIER_MONTHLY = {"STARTER": 2900, "CLASSIC": 4900, "RESERVE": 8900}
LOYALTY_TIER_DISCOUNT = {"RESERVE": 0.10, "CLASSIC": 0.05, "STARTER": 0.0}

REFERRAL_REWARD_POINTS = 500

# churn
W_RECENCY = 40
W_SKIP = 35
W_FAIL = 25
RECENCY_DIVISOR_DAYS = 60
SKIP_DIVISOR = 5
FAIL_DIVISOR = 3
CHURN_WINDOW_DAYS = 90

GIFT_WRAP_CENTS = 350


def volume_discount_pct(subtotal_cents):
    if subtotal_cents >= 20000:
        return 0.15
    if subtotal_cents >= 10000:
        return 0.10
    if subtotal_cents >= 5000:
        return 0.05
    return 0.0


def order_total(lines_with_sku, ship_zone, requested_redeem_points, loyalty_balance):
    """lines_with_sku: list of dicts {unit_price_cents, quantity, storage_class}.
    Returns dict of frozen monetary fields. Evaluation order is pinned."""
    subtotal = sum(l["unit_price_cents"] * l["quantity"] for l in lines_with_sku)
    disc_pct = volume_discount_pct(subtotal)
    discount = round_half_up(subtotal * disc_pct)
    discounted_subtotal = subtotal - discount

    perishable_line_count = sum(1 for l in lines_with_sku if l["storage_class"] == "PERISHABLE")
    handling = PERISHABLE_HANDLING_CENTS * perishable_line_count

    ship_base = ZONE_BASE[ship_zone]
    if perishable_line_count > 0:
        shipping = round_half_up(ship_base * PERISHABLE_SHIP_MULT)
    else:
        shipping = ship_base

    pre_redeem = discounted_subtotal + handling + shipping
    redeem_cap = int(LOYALTY_MAX_REDEEM_PCT * discounted_subtotal)  # floor
    redeemed = min(requested_redeem_points, redeem_cap, loyalty_balance)
    total = pre_redeem - redeemed

    return {
        "subtotal_cents": subtotal,
        "discount_cents": discount,
        "handling_cents": handling,
        "shipping_cents": shipping,
        "redeemed_points": redeemed,
        "total_cents": total,
    }


def loyalty_points_accrual(lines_with_sku):
    """Per-line round THEN sum. Perishable lines accrue 0."""
    total = 0
    for l in lines_with_sku:
        if l["storage_class"] == "AMBIENT":
            total += round_half_up(l["unit_price_cents"] * l["quantity"] * EARN_RATE_PER_CENT)
    return total


def provisional_charge(tier, home_zone):
    return TIER_MONTHLY[tier] + ZONE_BASE[home_zone]


def final_charge(effective_tier, home_zone):
    base = round_half_up(TIER_MONTHLY[effective_tier] * (1 - LOYALTY_TIER_DISCOUNT[effective_tier]))
    return base + ZONE_BASE[home_zone]


def churn_score(days_since_last_order, skip_count, failed_payment_count):
    a = min(1.0, days_since_last_order / RECENCY_DIVISOR_DAYS)
    b = min(1.0, skip_count / SKIP_DIVISOR)
    c = min(1.0, failed_payment_count / FAIL_DIVISOR)
    raw = W_RECENCY * a + W_SKIP * b + W_FAIL * c
    score = min(100, round_half_up(raw))
    return score


def churn_band(score):
    if score >= 70:
        return "CHURN_IMMINENT"
    if score >= 50:
        return "AT_RISK"
    return "OK"


def bulk_tier(line_subtotal):
    if line_subtotal >= 100000:
        return (0.20, 0.03)
    if line_subtotal >= 50000:
        return (0.12, 0.04)
    if line_subtotal >= 20000:
        return (0.07, 0.05)
    return (0.0, 0.06)


def corporate_bulk_quote(quantity, unit_price_cents, gift_box_count):
    line_subtotal = quantity * unit_price_cents
    disc_pct, handling_pct = bulk_tier(line_subtotal)
    discount = round_half_up(line_subtotal * disc_pct)
    discounted_subtotal = line_subtotal - discount
    handling = round_half_up(discounted_subtotal * handling_pct)
    gift_wrap = GIFT_WRAP_CENTS * gift_box_count
    total = discounted_subtotal + handling + gift_wrap
    return {
        "line_subtotal_cents": line_subtotal,
        "discount_cents": discount,
        "handling_cents": handling,
        "total_cents": total,
    }
