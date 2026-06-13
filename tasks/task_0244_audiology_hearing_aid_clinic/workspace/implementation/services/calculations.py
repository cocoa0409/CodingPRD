"""Pure calculation functions (SCAFFOLD §1.3, PRD §2.7/§3).

All monetary math is in integer cents. Where a fractional cent arises, it is
rounded HALF UP exactly once, at the point the calculation specifies. Decimal
is used for the rounding so we never touch IEEE-754 float drift.
"""

from decimal import Decimal, ROUND_HALF_UP

# Severity bands, least -> most severe (PRD §2.9 / §3.2).
SEVERITY_RANK = {"MILD": 1, "MODERATE": 2, "SEVERE": 3, "PROFOUND": 4}

# Trial window (PRD §3.3).
TRIAL_PERIOD_DAYS = 30

# Warranty settlement constants (SCAFFOLD §1.3 / PRD §3.8).
DAMAGE_DEDUCTIBLE_PCT = Decimal("0.25")
LOSS_DEDUCTIBLE_PCT = Decimal("0.50")
DEDUCTIBLE_CAP_CENTS = 40000

# Supply loyalty (PRD §3.9).
LOYALTY_THRESHOLD_CYCLES = 6
LOYALTY_DISCOUNT_PCT = Decimal("0.10")


def round_half_up(value):
    """Round a Decimal to the nearest whole cent, half up, returning an int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def classify_severity(ptag):
    """severity_classification: map a pure-tone average (dB HL) to a band using
    inclusive upper bounds. 25->NORMAL, 26..40->MILD, 41..55->MODERATE,
    56..70->SEVERE, 71..120->PROFOUND."""
    if ptag <= 25:
        return "NORMAL"
    elif ptag <= 40:
        return "MILD"
    elif ptag <= 55:
        return "MODERATE"
    elif ptag <= 70:
        return "SEVERE"
    else:
        return "PROFOUND"


def severity_rank(band):
    """Rank for indication comparison. NORMAL has no device rank; treat it as 0
    so no device (min MILD=1) is indicated for NORMAL."""
    if band == "NORMAL":
        return 0
    return SEVERITY_RANK[band]


def device_indicated(model_min_severity, eval_severity):
    """A device is indicated when eval severity rank >= model min_severity rank
    (PRD §2.9)."""
    return severity_rank(eval_severity) >= severity_rank(model_min_severity)


def benefit_waterfall(gross_cents, benefit):
    """Cap-then-pool waterfall (PRD §3.4). benefit is the AllowanceBenefit dict
    or None for self-pay. Returns allowance_applied_cents."""
    if benefit is None:
        return 0
    per_device_eligible = min(gross_cents, benefit["per_device_cap_cents"])
    pool_remaining = max(0, benefit["total_allowance_cents"] - benefit["consumed_allowance_cents"])
    return min(per_device_eligible, pool_remaining)


def patient_due(gross_cents, allowance_applied_cents, coinsurance_pct):
    """Allowance first, then coinsurance on the post-allowance remainder, a
    single half-up rounding (PRD §3.4). coinsurance_pct is 0 for self-pay."""
    post_allowance = gross_cents - allowance_applied_cents
    coinsurance_amount = round_half_up(Decimal(post_allowance) * Decimal(str(coinsurance_pct)))
    return post_allowance + coinsurance_amount


def return_refund(order, model, within_window, was_purchased):
    """return_refund (PRD §3.5).

    TRIAL->RETURNED (never purchased): refund = -restock_fee (a charge).
    PURCHASED->RETURNED within window: refund = patient_due - restock_fee.
    PURCHASED->RETURNED late: refund = 0 (rejected by precondition in practice).
    """
    restock = model["restock_fee_cents"]
    if not was_purchased:
        return -restock
    if within_window:
        return order["patient_due_cents"] - restock
    return 0


def warranty_settlement(claim_type, assessed_value_cents):
    """warranty_settlement (PRD §3.8). Returns (deductible_cents,
    clinic_cost_cents). Invariant: deductible + clinic_cost == assessed_value."""
    av = assessed_value_cents
    if claim_type == "DEFECT":
        deductible = 0
    elif claim_type == "DAMAGE":
        deductible = min(round_half_up(Decimal(av) * DAMAGE_DEDUCTIBLE_PCT), DEDUCTIBLE_CAP_CENTS)
    else:  # LOSS
        deductible = min(round_half_up(Decimal(av) * LOSS_DEDUCTIBLE_PCT), DEDUCTIBLE_CAP_CENTS)
    clinic_cost = av - deductible
    return deductible, clinic_cost


def supply_cycle_billing(cycle_index, unit_price_cents):
    """supply_cycle_billing (PRD §3.9). Loyalty discount applies strictly AFTER
    cycle 6 (cycle_index > 6)."""
    if cycle_index > LOYALTY_THRESHOLD_CYCLES:
        return round_half_up(Decimal(unit_price_cents) * (Decimal("1") - LOYALTY_DISCOUNT_PCT))
    return unit_price_cents
