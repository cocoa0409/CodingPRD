"""Rounding discipline (PRD §2.5) and the pure calculation kernels (PRD §3)."""

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

ZERO = Decimal(0)

_QUANT = {
    0: Decimal("1"),
    1: Decimal("0.1"),
    2: Decimal("0.01"),
    4: Decimal("0.0001"),
}


def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to ``places`` decimal places."""
    return D(value).quantize(_QUANT[places], rounding=ROUND_HALF_UP)


def rhu_int(value):
    """Round half up to a whole unit and return a Python int."""
    return int(rhu(value, 0))


def ceil_int(value):
    """Round up to the next whole unit (deposits only, PRD §2.5)."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_CEILING))


# --------------------------------------------------------------------------
# constants (SCAFFOLD calculations / PRD §3)
# --------------------------------------------------------------------------
UNACCOUNTED_TOLERANCE_LB = Decimal("0.05")
REVISION_LIMIT = 2
AMEND_LIMIT = 2

TIER_1_CEILING_CENTS = 800
TIER_2_CEILING_CENTS = 1600
MARGIN_BUMP_TIER_2 = Decimal("0.02")
MARGIN_BUMP_TIER_3 = Decimal("0.04")
MARGIN_CAP_PCT = Decimal("0.60")
STANDARD_SALABLE_YIELD_PCT = Decimal("0.62")
REPRICE_THRESHOLD_PCT = Decimal("0.02")

FACING_CAPACITY_LB = {
    "GROUND": Decimal("4.0"),
    "WHOLE_MUSCLE": Decimal("6.0"),
    "VAC_PACKED": Decimal("8.0"),
}
DEMAND_UPLIFT = Decimal("1.15")
CARRY_CAP_FACTOR = Decimal("0.30")
RESTRICTED_HALVING = Decimal("0.5")
FILL_OVERAGE_CAP = Decimal("1.25")

REGRIND_GENERATION_LIMIT = 1
CONSECUTIVE_FAILURE_THRESHOLD = 2
ESCALATION_MINUTES = 240
CANCEL_REFUND_FACTOR = Decimal("0.5")


# --------------------------------------------------------------------------
# pricing (PRD §3.4) — exactly one pass, tier never re-evaluated
# --------------------------------------------------------------------------

def shelf_price_from_basis(cost_basis_cents, base_margin_pct):
    basis = D(cost_basis_cents)
    base_margin = D(base_margin_pct)

    first_pass = rhu_int(basis / (Decimal(1) - base_margin))

    if first_pass < TIER_1_CEILING_CENTS:
        bump = ZERO
    elif first_pass < TIER_2_CEILING_CENTS:
        bump = MARGIN_BUMP_TIER_2
    else:
        bump = MARGIN_BUMP_TIER_3

    effective = base_margin + bump
    if effective > MARGIN_CAP_PCT:
        effective = MARGIN_CAP_PCT

    second_pass = rhu_int(basis / (Decimal(1) - effective))

    # Nudge up to the next whole cent whose last digit is 9 (strictly after
    # rounding, never before).
    return second_pass + ((9 - (second_pass % 10)) % 10)


def provisional_cost_basis(invoice_cost_cents, net_weight_lb):
    """Freight and vendor allowance are deliberately excluded (PRD §3.4)."""
    per_pound = D(invoice_cost_cents) / D(net_weight_lb)
    return rhu(per_pound / STANDARD_SALABLE_YIELD_PCT, 4)


def price_variance_pct(final_cents, provisional_cents):
    provisional = D(provisional_cents)
    if provisional <= 0:
        return rhu(0, 4)
    return rhu((D(final_cents) - provisional) / provisional, 4)


def exceeds_reprice_threshold(new_price_cents, active_price_cents):
    active = D(active_price_cents)
    if active <= 0:
        return False
    delta = abs(D(new_price_cents) - active)
    return (delta / active) > REPRICE_THRESHOLD_PCT


# --------------------------------------------------------------------------
# required fill (PRD §3.7 / §3.6)
# --------------------------------------------------------------------------

def required_fill_lb(facings, expected_movement_lb, product_class,
                     shelf_life_days, posture):
    facing_lb = FACING_CAPACITY_LB[product_class]
    presentation = D(facings) * facing_lb
    demand = D(expected_movement_lb) * DEMAND_UPLIFT
    carry_cap = D(expected_movement_lb) * D(shelf_life_days) * CARRY_CAP_FACTOR
    base = max(presentation, min(demand, carry_cap))
    if posture == "SALES_RESTRICTED":
        return rhu(rhu(base, 2) * RESTRICTED_HALVING, 2)
    return rhu(base, 2)


# --------------------------------------------------------------------------
# markdown floor (PRD §3.6)
# --------------------------------------------------------------------------

def markdown_floor_cents(yield_adjusted_cost_per_lb_cents, markdown_floor_pct):
    return rhu_int(D(yield_adjusted_cost_per_lb_cents)
                   * (Decimal(1) + D(markdown_floor_pct)))


def markdown_give_up_cents(event_lb, active_price_cents, markdown_price_cents):
    return rhu_int(D(event_lb) * (D(active_price_cents) - D(markdown_price_cents)))


# --------------------------------------------------------------------------
# deposits (PRD §3.8)
# --------------------------------------------------------------------------

def deposit_cents(quoted_price_per_lb_cents, requested_weight_lb, deposit_rate):
    extended = D(quoted_price_per_lb_cents) * D(requested_weight_lb)
    return ceil_int(extended * D(deposit_rate))


def cancel_refund_cents(deposit):
    return rhu_int(D(deposit) * CANCEL_REFUND_FACTOR)
