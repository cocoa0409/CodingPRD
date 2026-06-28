"""Pure calculation rules (SCAFFOLD §1.3, PRD §2.10 + §3).

All monetary math is integer cents. Every percentage is applied by integer
floor division: multiply first, then // 100 (rounding toward zero).
"""

# Group-discount tiers (reservation_pricing).
TIER_LARGE_MIN_SEATS = 8
TIER_LARGE_PCT = 15
TIER_MID_MIN_SEATS = 4
TIER_MID_PCT = 10

# Cancellation credit ladder.
FULL_CREDIT_MIN_HOURS = 48
HALF_CREDIT_MIN_HOURS = 24
FULL_CREDIT_PCT = 100
HALF_CREDIT_PCT = 50


def group_discount_pct(seats):
    if seats >= TIER_LARGE_MIN_SEATS:
        return TIER_LARGE_PCT
    if seats >= TIER_MID_MIN_SEATS:
        return TIER_MID_PCT
    return 0


def reservation_pricing(seats, price_cents_per_seat, kit_fee_cents, include_supply_kit):
    """Return (base_cents, group_discount_pct, kit_charge_cents, total_cents).

    Rounding order is pinned discount-then-add: apply the percentage discount
    to the whole-cent base FIRST (integer floor division), THEN add the kit
    charge. The kit charge is never discounted.
    """
    base_cents = seats * price_cents_per_seat
    pct = group_discount_pct(seats)
    discounted_base = base_cents - (base_cents * pct // 100)
    kit_charge_cents = (seats * kit_fee_cents) if include_supply_kit else 0
    total_cents = discounted_base + kit_charge_cents
    return base_cents, pct, kit_charge_cents, total_cents


def hours_before(start_dt, now_dt):
    """floor((start - now) / 3600s); may be negative."""
    delta_seconds = (start_dt - now_dt).total_seconds()
    # floor toward negative infinity for negative values too.
    import math
    return math.floor(delta_seconds / 3600)


def credit_pct_for_hours(hours):
    if hours >= FULL_CREDIT_MIN_HOURS:
        return FULL_CREDIT_PCT
    if hours >= HALF_CREDIT_MIN_HOURS:
        return HALF_CREDIT_PCT
    return 0


def cancellation_credit(total_cents, hours):
    pct = credit_pct_for_hours(hours)
    return pct, total_cents * pct // 100


def donation_cents(base_sum, fundraiser_donation_pct):
    """Sum-then-multiply: aggregate base first, apply pct once, then floor."""
    return fundraiser_donation_pct * base_sum // 100
