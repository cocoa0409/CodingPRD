"""Calculation rules — implement SCAFFOLD §1.3 verbatim."""

from decimal import Decimal

from helpers import to_dec, round_half_up_2, round_down_2


# ----- calc_allocation_total --------------------------------------------------

ANNUAL_REDUCTION_FACTOR = Decimal("0.97")


def calc_allocation_total(method, activity_volume, benchmark_factor,
                          historical_baseline, free_paid_ratio):
    """Returns (total_quota, free_quota, paid_quota) as Decimals (2dp)."""
    fpr = to_dec(free_paid_ratio)
    if method == "INDUSTRY_BENCHMARK":
        total = round_half_up_2(to_dec(activity_volume) * to_dec(benchmark_factor))
    elif method == "HISTORICAL_EMISSION":
        total = round_half_up_2(to_dec(historical_baseline) * ANNUAL_REDUCTION_FACTOR)
    else:
        raise ValueError(f"Unknown allocation method: {method}")
    free_quota = round_half_up_2(total * fpr)
    paid_quota = round_half_up_2(total - free_quota)
    return total, free_quota, paid_quota


def calc_revised_allocation(revised_total_quota, free_paid_ratio):
    """Recompute free/paid given a revised total. Returns (total, free, paid)."""
    total = round_half_up_2(revised_total_quota)
    free_quota = round_half_up_2(total * to_dec(free_paid_ratio))
    paid_quota = round_half_up_2(total - free_quota)
    return total, free_quota, paid_quota


# ----- calc_total_reported_emissions ------------------------------------------

def calc_line_source_amount(activity_data, emission_factor):
    """Per-line: round_half_up(activity_data * emission_factor, 2). Returns Decimal."""
    return round_half_up_2(to_dec(activity_data) * to_dec(emission_factor))


def calc_total_reported_emissions(lines):
    """Sum of per-line rounded source_amounts. Sum is itself 2dp; no extra round."""
    s = Decimal("0")
    for l in lines:
        s += to_dec(l["source_amount"])
    # Outer round is a no-op (sum of 2dp is 2dp); explicit for determinism.
    return round_half_up_2(s)


# ----- calc_verified_emissions ------------------------------------------------

def calc_total_verified_emissions(lines):
    """Sum of per-line verified_amount values. Sum NOT re-rounded."""
    s = Decimal("0")
    for l in lines:
        if l.get("verified_amount") is None:
            continue
        s += to_dec(l["verified_amount"])
    return s


def calc_cross_check_delta_pct(total_reported, total_verified):
    """abs(verified - reported) / reported * 100, round_half_up 2dp.
    If reported is zero, return Decimal('0')."""
    rep = to_dec(total_reported)
    if rep == 0:
        return Decimal("0.00")
    diff = abs(to_dec(total_verified) - rep)
    return round_half_up_2(diff / rep * Decimal("100"))


# ----- calc_trade_fee ---------------------------------------------------------

TIER_BASE_RATE_BY_CHANNEL = {
    "EXCHANGE": Decimal("0.0010"),
    "BLOCK": Decimal("0.0006"),
    "OTC": Decimal("0.0008"),
}
TIER1_CAP = Decimal("100000")
TIER2_CAP = Decimal("1000000")
TIER2_DISCOUNT = Decimal("0.80")
TIER3_DISCOUNT = Decimal("0.60")


def calc_trade_fee(channel, quantity, price):
    """Returns (gross_value, fee_per_side) as Decimals (2dp).

    The fee per side is computed using marginal-tier discounts; an average-rate
    interpretation is forbidden by the scaffold.
    """
    gross_value = round_half_up_2(to_dec(quantity) * to_dec(price))
    base_rate = TIER_BASE_RATE_BY_CHANNEL[channel]
    # Marginal tier portions:
    tier1 = min(gross_value, TIER1_CAP)
    tier2 = max(Decimal("0"), min(gross_value, TIER2_CAP) - TIER1_CAP)
    tier3 = max(Decimal("0"), gross_value - TIER2_CAP)
    raw_fee = (
        tier1 * base_rate
        + tier2 * base_rate * TIER2_DISCOUNT
        + tier3 * base_rate * TIER3_DISCOUNT
    )
    fee_per_side = round_half_up_2(raw_fee)
    return gross_value, fee_per_side


# ----- calc_compliance_balance ------------------------------------------------

def calc_compliance_balance(verified, declared_offset_quota,
                            declared_offset_ccer, declared_borrow_amount):
    """Returns (deficit_amount, surplus_amount) Decimals (2dp)."""
    v = to_dec(verified)
    offset_total = (to_dec(declared_offset_quota)
                    + to_dec(declared_offset_ccer)
                    + to_dec(declared_borrow_amount))
    deficit = round_half_up_2(max(Decimal("0"), v - offset_total))
    surplus = round_half_up_2(max(Decimal("0"), offset_total - v))
    return deficit, surplus


# ----- calc_penalty_amount ----------------------------------------------------

JURISDICTION_PENALTY_RATE = {
    "JD_ALPHA": {"MINOR": Decimal("100.00"), "MODERATE": Decimal("200.00"), "SEVERE": Decimal("500.00")},
    "JD_BETA":  {"MINOR": Decimal("80.00"),  "MODERATE": Decimal("180.00"), "SEVERE": Decimal("450.00")},
    "JD_GAMMA": {"MINOR": Decimal("120.00"), "MODERATE": Decimal("250.00"), "SEVERE": Decimal("600.00")},
}
SEVERITY_MINOR_BREAKPOINT = Decimal("0.05")
SEVERITY_MODERATE_BREAKPOINT = Decimal("0.20")
MANDATORY_DEDUCTION_MULTIPLIER = Decimal("1.5")


def classify_severity(deficit_pct):
    """Severity by exclusive lower-bound thresholds (PRD §3.6):
       deficit_pct < 0.05  -> MINOR
       deficit_pct < 0.20  -> MODERATE
       else                -> SEVERE
    Boundary cases: 0.05 -> MODERATE, 0.20 -> SEVERE."""
    p = to_dec(deficit_pct)
    if p < SEVERITY_MINOR_BREAKPOINT:
        return "MINOR"
    if p < SEVERITY_MODERATE_BREAKPOINT:
        return "MODERATE"
    return "SEVERE"


def calc_penalty(deficit_amount, verified_emissions, jurisdiction_code):
    """Returns (severity, penalty_rate, penalty_amount, mandatory_deduction)."""
    deficit = to_dec(deficit_amount)
    v = to_dec(verified_emissions)
    deficit_pct = (deficit / v) if v != 0 else Decimal("0")
    severity = classify_severity(deficit_pct)
    penalty_rate = JURISDICTION_PENALTY_RATE[jurisdiction_code][severity]
    penalty_amount = round_half_up_2(deficit * penalty_rate)
    mandatory_deduction = round_half_up_2(deficit * MANDATORY_DEDUCTION_MULTIPLIER)
    return severity, penalty_rate, penalty_amount, mandatory_deduction


# ----- calc_annual_settlement -------------------------------------------------

CARRY_FORWARD_CAP_PCT = Decimal("0.10")
REPURCHASE_FLOOR_PRICE = Decimal("30.00")


def calc_annual_settlement(opening_quota, net_traded_quota, retired_quota,
                           mandatory_deductions, next_cycle_allocation_total):
    """Compute the settlement waterfall.

    Returns dict with closing_balance, carry_forward_amount, repurchase_amount,
    deficit_purchase_amount as Decimals (2dp).
    """
    closing = round_half_up_2(
        to_dec(opening_quota)
        + to_dec(net_traded_quota)
        - to_dec(retired_quota)
        - to_dec(mandatory_deductions)
    )
    carry_cap = round_half_up_2(to_dec(next_cycle_allocation_total) * CARRY_FORWARD_CAP_PCT)
    if closing >= 0:
        carry_forward = min(closing, carry_cap)
        repurchase = round_half_up_2(closing - carry_forward)
        deficit_purchase = Decimal("0.00")
    else:
        carry_forward = Decimal("0.00")
        repurchase = Decimal("0.00")
        deficit_purchase = round_half_up_2(-closing)
    return {
        "closing_balance": closing,
        "carry_forward_amount": carry_forward,
        "repurchase_amount": repurchase,
        "deficit_purchase_amount": deficit_purchase,
    }


# ----- CCER cap & borrow cap (validation helpers) -----------------------------

def ccer_cap_value(verified_emissions, ccer_cap_pct):
    """floor-to-2dp of verified * ccer_cap_pct."""
    return round_down_2(to_dec(verified_emissions) * to_dec(ccer_cap_pct))


def borrow_cap_value(verified_emissions):
    """floor-to-2dp of verified * 0.05."""
    return round_down_2(to_dec(verified_emissions) * Decimal("0.05"))
