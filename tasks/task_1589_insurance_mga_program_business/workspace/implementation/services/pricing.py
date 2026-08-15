"""Premium and earned-premium calculations (scaffold section 1.3).

policy_premium: clamped mod, round_half_up at each stated step, integer cents.
earned_premium: whole-day pro-rata with flat-cancel and short-rate variants.
"""
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("1")
PCT2 = Decimal("0.01")

MOD_CLAMP_LOW = Decimal("0.75")
MOD_CLAMP_HIGH = Decimal("1.25")
CANCELLATION_FEE_CENTS = 2500
SHORT_RATE_FACTOR = Decimal("1.10")


def round_cents(d):
    return int(d.quantize(CENT, rounding=ROUND_HALF_UP))


def ratio_pct(numerator_cents, denominator_cents):
    """Percentage at 2 decimal places, round_half_up; None when denominator is 0."""
    if denominator_cents == 0:
        return None
    return (Decimal(numerator_cents) * 100 / Decimal(denominator_cents)).quantize(
        PCT2, rounding=ROUND_HALF_UP
    )


def compute_premium_cents(exposure_units, base_rate_cents, experience_mod,
                          policy_fee_cents, min_premium_cents, commission_rate_pct):
    """provisional and final_audit variants share this formula.

    clamped_mod = max(0.75, min(1.25, experience_mod))   # clamp BEFORE multiply
    raw_cents   = round_half_up(exposure_units * base_rate_cents * clamped_mod)
    pre_floor   = raw_cents + policy_fee_cents
    gross       = max(pre_floor, min_policy_premium_cents)
    commission  = round_half_up(gross * commission_rate_pct)
    """
    mod = Decimal(str(experience_mod))
    clamped = max(MOD_CLAMP_LOW, min(MOD_CLAMP_HIGH, mod))
    raw = round_cents(Decimal(exposure_units) * Decimal(base_rate_cents) * clamped)
    gross = max(raw + policy_fee_cents, min_premium_cents)
    commission = round_cents(Decimal(gross) * Decimal(str(commission_rate_pct)))
    return gross, commission


def _whole_days(delta):
    """Whole days of a timedelta (floor); callers clamp into range."""
    return delta.days


def pro_rata_earned_cents(gross_premium_cents, effective_from, effective_to, as_of):
    term_days = _whole_days(effective_to - effective_from)
    if term_days < 1:
        term_days = 1
    elapsed = _whole_days(min(as_of, effective_to) - effective_from)
    elapsed = max(0, min(term_days, elapsed))
    return round_cents(
        Decimal(gross_premium_cents) * Decimal(elapsed) / Decimal(term_days)
    )


def is_flat_cancel(policy):
    return policy["cancellation_date"] <= policy["effective_from"]


def cancellation_earned_cents(policy):
    """Earned premium at cancellation.

    flat cancel (cancellation_date <= effective_from): earned = 0, fee waived.
    INSURED_REQUEST (non-flat): short-rate = round_half_up(pro_rata * 1.10).
    CARRIER_REQUEST / NON_PAYMENT: plain pro-rata.
    """
    if is_flat_cancel(policy):
        return 0
    earned = pro_rata_earned_cents(
        policy["gross_premium_cents"],
        policy["effective_from"],
        policy["effective_to"],
        policy["cancellation_date"],
    )
    if policy["cancellation_reason"] == "INSURED_REQUEST":
        earned = round_cents(Decimal(earned) * SHORT_RATE_FACTOR)
    return earned


def evaluation_earned_cents(policy, clock):
    """Earned basis contribution for a loss evaluation: pro-rata as of the
    evaluation clock; CANCELLED policies contribute the premium crystallized
    at cancellation (its variant was selected at cancellation time)."""
    if policy["status"] == "CANCELLED":
        return policy["earned_premium_cents"]
    return pro_rata_earned_cents(
        policy["gross_premium_cents"],
        policy["effective_from"],
        policy["effective_to"],
        clock,
    )
