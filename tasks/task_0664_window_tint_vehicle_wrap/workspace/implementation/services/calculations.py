"""Calculation rules: line pricing, quote totals, cure projection, warranty,
fleet credit. All monetary math is integer cents with round-half-up.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

# Coverage factors
COVERAGE_FACTORS = {
    "FULL": Decimal("1.00"),
    "PARTIAL": Decimal("0.60"),
    "ACCENT": Decimal("0.35"),
}

# Size surcharges (cents)
SIZE_SURCHARGE = {
    "SEDAN": 0,
    "SUV": 15000,
    "TRUCK": 25000,
}

DEPOSIT_RATE_BPS = 2500
QUOTE_TTL_DAYS = 30
INSTALLER_REST_BUFFER_MINUTES = 45

RUSH_BPS_HIGH = 500    # net >= 100000
RUSH_BPS_MID = 800     # 50000 <= net < 100000
RUSH_BPS_LOW = 1200    # net < 50000
RUSH_TIER_HIGH_CENTS = 100000
RUSH_TIER_MID_CENTS = 50000


def round_half_up(value):
    """Round a Decimal to whole cents using round-half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def line_item_price(base_rate_cents, coverage, price_multiplier_bps, size_surcharge_cents):
    """calc line_item_price (scaffold §1.3).

    raw_cents = base_rate_cents * coverage_factor * material_mult
    priced_cents = round_half_up(raw_cents)      # round the product FIRST
    line_total_cents = priced_cents + size_surcharge_cents  # add integer surcharge after
    """
    coverage_factor = COVERAGE_FACTORS[coverage]
    material_mult = Decimal(price_multiplier_bps) / Decimal(10000)
    raw = Decimal(base_rate_cents) * coverage_factor * material_mult
    priced_cents = round_half_up(raw)
    return priced_cents + int(size_surcharge_cents)


def _rush_bps(net_cents):
    if net_cents >= RUSH_TIER_HIGH_CENTS:
        return RUSH_BPS_HIGH
    if net_cents >= RUSH_TIER_MID_CENTS:
        return RUSH_BPS_MID
    return RUSH_BPS_LOW


def quote_total(line_totals, fleet_discount_bps, rushed):
    """calc quote_total (scaffold §1.3). Evaluation order is pinned:
    subtotal -> discount (sum-then-round) -> net -> rush (net tier) -> deposit.

    Returns a dict of the six computed money fields.
    """
    subtotal_cents = sum(line_totals)
    discount_cents = round_half_up(
        Decimal(subtotal_cents) * Decimal(fleet_discount_bps) / Decimal(10000)
    )
    net_cents = subtotal_cents - discount_cents

    if rushed:
        bps = _rush_bps(net_cents)
        rush_fee_cents = round_half_up(
            Decimal(net_cents) * Decimal(bps) / Decimal(10000)
        )
    else:
        rush_fee_cents = 0

    total_due_cents = net_cents + rush_fee_cents
    deposit_required_cents = round_half_up(
        Decimal(net_cents) * Decimal(DEPOSIT_RATE_BPS) / Decimal(10000)
    )

    return {
        "subtotal_cents": subtotal_cents,
        "discount_cents": discount_cents,
        "net_cents": net_cents,
        "rush_fee_cents": rush_fee_cents,
        "total_due_cents": total_due_cents,
        "deposit_required_cents": deposit_required_cents,
    }


def estimated_cure_complete_at(scheduled_start, duration_minutes, cure_hours):
    """ESTIMATED cure: scheduled_start + duration_minutes + cure_hours."""
    return scheduled_start + timedelta(minutes=duration_minutes) + timedelta(hours=cure_hours)


def actual_cure_complete_at(actual_completed_at, cure_hours):
    """ACTUAL cure: actual_completed_at + cure_hours."""
    return actual_completed_at + timedelta(hours=cure_hours)


def warranty_expires_at(actual_completed_at, warranty_days):
    """warranty_expires_at = actual_completed_at + warranty_days."""
    return actual_completed_at + timedelta(days=warranty_days)
