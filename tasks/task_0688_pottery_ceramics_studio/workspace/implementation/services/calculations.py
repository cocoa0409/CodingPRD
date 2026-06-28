"""Calculation rules (SCAFFOLD §1.3, PRD §2.5, §3.7, §3.8, §3.10, §3.6, §3.1).

All money is integer cents. Wherever a percentage/rate produces a fractional
cent, the single rounding step uses round-half-up (Decimal, ROUND_HALF_UP).
Points are integers, floored at each described step.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

# ---- Constants (verbatim from SCAFFOLD §1.3) --------------------------------

STUDIO_FEE_PER_PAINTER_CENTS = 1000
TIER_DISCOUNT_PCT = {"BRONZE": Decimal("0.0"), "SILVER": Decimal("0.05"), "GOLD": Decimal("0.10")}
POINT_REDEEM_VALUE_CENTS = 1

POINTS_PER_CENT_DIVISOR = 100
GOLD_BONUS_THRESHOLD_CENTS = 10000
BONUS_MULTIPLIER = Decimal("1.5")

BULK_QTY_THRESHOLD = 3
BULK_DISCOUNT_PCT = Decimal("0.10")

PACKAGE_RATE_CENTS = {"BASIC": 4500, "DELUXE": 8000}
PACKAGE_MIN_GUESTS = {"BASIC": 6, "DELUXE": 10}
DEPOSIT_RATE = Decimal("0.25")

ENROLL_POINTS_PER_CENT_DIVISOR = 100
LONG_SERIES_THRESHOLD = 6
LONG_SERIES_BONUS = 50

SILVER_THRESHOLD = 500
GOLD_THRESHOLD = 2000


def round_half_up(value):
    """Round a Decimal to the nearest whole integer, half rounds up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---- supplies_charge (SCAFFOLD calc supplies_charge, PRD §3.7) ---------------

def line_charge_cents(qty, unit_price_cents):
    """Per-line charge with a bulk break at qty >= 3.

    line_charge = qty * unit_price; if qty >= 3 multiply by 0.9 and round-half-up
    the discounted line. Rounding is per line, after the bulk multiplier.
    """
    raw = qty * unit_price_cents
    if qty >= BULK_QTY_THRESHOLD:
        return round_half_up(Decimal(raw) * (Decimal("1") - BULK_DISCOUNT_PCT))
    return raw


# ---- settle_visit_charge (SCAFFOLD calc settle_visit_charge, PRD §3.8) -------

def tier_discount_cents(bisque_subtotal_cents, member_tier):
    """Tier discount on bisque only; round the single product once, half-up.

    member_tier may be None for an anonymous visit -> 0 discount.
    """
    if not member_tier:
        return 0
    pct = TIER_DISCOUNT_PCT.get(member_tier, Decimal("0"))
    if pct == 0:
        return 0
    return round_half_up(Decimal(bisque_subtotal_cents) * pct)


def settle_visit_charge(studio_fee_cents, bisque_subtotal_cents,
                        supplies_subtotal_cents, member_tier, points_redeemed):
    """Settled variant. Returns (settled_total_cents, discount_cents,
    tier_discount, redemption_value, subtotal_before_discount)."""
    subtotal_before_discount = (
        studio_fee_cents + bisque_subtotal_cents + supplies_subtotal_cents
    )
    tier_disc = tier_discount_cents(bisque_subtotal_cents, member_tier)
    redemption_value = points_redeemed * POINT_REDEEM_VALUE_CENTS
    discount_cents = tier_disc + redemption_value
    settled_total_cents = max(0, subtotal_before_discount - discount_cents)
    return settled_total_cents, discount_cents, tier_disc, redemption_value, subtotal_before_discount


def provisional_total(studio_fee_cents, bisque_subtotal_cents, supplies_subtotal_cents):
    """Provisional variant: gross sum, NO discount, NO redemption."""
    return studio_fee_cents + bisque_subtotal_cents + supplies_subtotal_cents


# ---- visit_points_earned (SCAFFOLD calc visit_points_earned, PRD §3.8) -------

def visit_points_earned(net_spend_cents):
    """Points from post-discount net spend. 1 pt per 100 cents (floor); a 1.5x
    bonus (floored) applies only when net_spend >= 10000 cents."""
    base_points = net_spend_cents // POINTS_PER_CENT_DIVISOR
    if net_spend_cents >= GOLD_BONUS_THRESHOLD_CENTS:
        return int((Decimal(base_points) * BONUS_MULTIPLIER).to_integral_value(rounding=ROUND_FLOOR))
    return base_points


# ---- party_deposit (SCAFFOLD calc party_deposit, PRD §3.6) -------------------

def party_deposit(package_tier, guest_count):
    """Returns (package_total_cents, deposit_due_cents)."""
    per_head = PACKAGE_RATE_CENTS[package_tier]
    package_total_cents = guest_count * per_head
    deposit_due_cents = round_half_up(Decimal(package_total_cents) * DEPOSIT_RATE)
    return package_total_cents, deposit_due_cents


# ---- enrollment_points_earned (SCAFFOLD calc enrollment_points_earned) -------

def enrollment_points_earned(amount_paid_cents, session_count):
    """Class loyalty: base = floor(amount/100); +50 flat when session_count>=6."""
    base_points = amount_paid_cents // ENROLL_POINTS_PER_CENT_DIVISOR
    if session_count >= LONG_SERIES_THRESHOLD:
        return base_points + LONG_SERIES_BONUS
    return base_points


# ---- member_tier (SCAFFOLD calc member_tier, PRD §3.1) -----------------------

def member_tier(lifetime_points_earned):
    """Tier by inclusive threshold: >=2000 GOLD, >=500 SILVER, else BRONZE."""
    if lifetime_points_earned >= GOLD_THRESHOLD:
        return "GOLD"
    if lifetime_points_earned >= SILVER_THRESHOLD:
        return "SILVER"
    return "BRONZE"
