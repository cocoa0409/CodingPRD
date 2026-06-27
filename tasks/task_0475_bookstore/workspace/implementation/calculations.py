"""All monetary/point calculations (PRD §3, SCAFFOLD Table 1.3).

Money is integer cents. Fractional cents round half-up. Rounding order is pinned
per calculation. We use Decimal to avoid binary float error.
"""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value):
    """Round a Decimal to a whole integer using round-half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---- (1) buyback_offer -----------------------------------------------------
BUYBACK_BASE_RATE = Decimal("0.30")
BUYBACK_DEMAND_BONUS = Decimal("0.10")
GRADE_MULT = {
    "LIKE_NEW": Decimal("1.00"),
    "GOOD": Decimal("0.70"),
    "FAIR": Decimal("0.40"),
}


def buyback_line_offer(list_price_cents, demand_flag, condition_grade, quantity):
    """Per-copy offer rounded half-up, then * quantity. Returns line_offer_cents."""
    rate = BUYBACK_BASE_RATE + (BUYBACK_DEMAND_BONUS if demand_flag == "HIGH" else Decimal("0"))
    grade = GRADE_MULT[condition_grade]
    per_copy = round_half_up(Decimal(list_price_cents) * rate * grade)
    return per_copy * quantity


# ---- (2) order_pricing -----------------------------------------------------
GOLD_DISCOUNT_RATE = Decimal("0.05")


def order_pricing(subtotal_cents, tier, credit_redeemed_cents):
    """Returns (member_discount_cents, net_paid_cents). Order pinned."""
    if tier == "GOLD":
        member_discount = round_half_up(Decimal(subtotal_cents) * GOLD_DISCOUNT_RATE)
    else:
        member_discount = 0
    net_paid = subtotal_cents - member_discount - credit_redeemed_cents
    if net_paid < 0:
        net_paid = 0
    return member_discount, net_paid


# ---- (3) loyalty_points ----------------------------------------------------
MONTHLY_POINT_CAP = 1000
EARN_DIVISOR = 100


def loyalty_points(net_paid_cents, tier):
    """Integer floor on divisor, * tier multiplier, capped at MONTHLY_POINT_CAP."""
    tier_mult = 2 if tier == "GOLD" else 1
    base = net_paid_cents // EARN_DIVISOR  # integer floor
    pts = base * tier_mult
    return min(pts, MONTHLY_POINT_CAP)


# ---- (4) consignment_payout ------------------------------------------------
def consignment_payout(units_sold_before, sale_price_cents):
    """Tier selected from units_sold_to_date BEFORE this copy is counted."""
    u = units_sold_before
    if u < 10:
        commission_rate = Decimal("0.40")
    elif u < 25:
        commission_rate = Decimal("0.35")
    else:
        commission_rate = Decimal("0.30")
    return round_half_up(Decimal(sale_price_cents) * (Decimal("1") - commission_rate))


# ---- (5) special_order_quote ----------------------------------------------
DISTRIBUTOR_LEAD_DAYS = 7
POD_LEAD_DAYS = 3
POD_MARKUP = Decimal("1.20")


def special_order_quote(list_price_cents, fulfillment_method, current_clock):
    """Returns (quoted_unit_cents, promised_eta_datetime)."""
    from datetime import timedelta
    if fulfillment_method == "DISTRIBUTOR":
        quoted_unit = round_half_up(Decimal(list_price_cents) * Decimal("1.00"))
        eta = current_clock + timedelta(days=DISTRIBUTOR_LEAD_DAYS)
    else:  # POD
        quoted_unit = round_half_up(Decimal(list_price_cents) * POD_MARKUP)
        eta = current_clock + timedelta(days=POD_LEAD_DAYS)
    return quoted_unit, eta


# ---- (6) return_credit -----------------------------------------------------
PUBLISHER_CREDIT_RATE = Decimal("0.50")


def return_credit(list_price_cents, quantity):
    """Returns (credit_unit_cents, credit_total_cents). Round per-unit, then * qty."""
    credit_unit = round_half_up(Decimal(list_price_cents) * PUBLISHER_CREDIT_RATE)
    return credit_unit, credit_unit * quantity


# ---- (7) ticket_price ------------------------------------------------------
HIGH_DEMAND_SURCHARGE = Decimal("0.25")


def ticket_price(base_price_cents, demand_flag, tier):
    """Order pinned: surcharge from base -> add -> discount from gross -> subtract."""
    if demand_flag == "HIGH":
        surcharge = round_half_up(Decimal(base_price_cents) * HIGH_DEMAND_SURCHARGE)
    else:
        surcharge = 0
    gross = base_price_cents + surcharge
    if tier == "GOLD":
        discount = round_half_up(Decimal(gross) * GOLD_DISCOUNT_RATE)
    else:
        discount = 0
    price = gross - discount
    if price < 0:
        price = 0
    return price
