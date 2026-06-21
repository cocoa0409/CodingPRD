from decimal import Decimal, ROUND_HALF_UP

# Constants pinned by the PRD / scaffold.
RUSH_HOUR_STEP = Decimal("0.50")
MULTIPLIER_CAP = Decimal("2.50")
BOOKING_FEE_CENTS = 150
DRIVER_SHARE = Decimal("0.80")

# Heat-map band edges (lower-inclusive, upper-exclusive).
COOL_MAX_EXCLUSIVE = Decimal("1.25")
WARM_MAX_EXCLUSIVE = Decimal("1.75")
HOT_MAX_EXCLUSIVE = Decimal("2.50")


def _round2(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _round_cents(x):
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def surge_multiplier(observed_demand, observed_supply, is_rush_hour):
    """Returns (ratio: Decimal 2dp, multiplier: Decimal 2dp, capped: bool)."""
    effective_supply = max(int(observed_supply), 1)
    ratio = _round2(Decimal(int(observed_demand)) / Decimal(effective_supply))

    if ratio < Decimal("1.00"):
        raw = Decimal("1.00")
    elif ratio < Decimal("2.00"):
        raw = Decimal("1.50")
    elif ratio < Decimal("3.00"):
        raw = Decimal("2.00")
    else:
        raw = Decimal("2.50")

    if is_rush_hour:
        raw = raw + RUSH_HOUR_STEP

    multiplier = min(raw, MULTIPLIER_CAP)
    capped = raw > MULTIPLIER_CAP
    return _round2(ratio), _round2(multiplier), capped


def heat_level(multiplier):
    m = Decimal(str(multiplier))
    if m < COOL_MAX_EXCLUSIVE:
        return "COOL"
    elif m < WARM_MAX_EXCLUSIVE:
        return "WARM"
    elif m < HOT_MAX_EXCLUSIVE:
        return "HOT"
    return "BLAZING"


def _surged(quoted_base_fare_cents, quoted_multiplier):
    return _round_cents(Decimal(int(quoted_base_fare_cents)) * Decimal(str(quoted_multiplier)))


def trip_final_fare(quoted_base_fare_cents, quoted_multiplier):
    surged = _surged(quoted_base_fare_cents, quoted_multiplier)
    return surged + BOOKING_FEE_CENTS


def driver_payout(quoted_base_fare_cents, quoted_multiplier):
    surged = _surged(quoted_base_fare_cents, quoted_multiplier)
    return _round_cents(Decimal(surged) * DRIVER_SHARE)


def dispute_refund(requested_refund_cents, final_fare_cents, refunded_cents):
    net_paid = int(final_fare_cents) - int(refunded_cents)
    if net_paid <= 0:
        return 0
    return min(int(requested_refund_cents), net_paid)
