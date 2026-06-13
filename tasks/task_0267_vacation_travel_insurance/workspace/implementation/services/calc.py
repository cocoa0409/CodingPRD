"""Calculation rules (PRD §3, scaffold §1.3). All money in whole integer cents.

Rounding directions (PRD §2.6) are deliberate and differ per calculation:
  - premium components: ceil per term independently
  - cancellation reimbursement + CFAR pct: floor
  - short-rate proration: floor
  - aggregate-limit pinning: floor
  - per-item baggage depreciation: round half up
  - day counts: floor or ceil as the calculation names
"""
import math
from decimal import Decimal, ROUND_HALF_UP

SHORT_RATE_ADMIN_FEE_CENTS = 2500
MIN_DELAY_HOURS = 12
DELAY_MERGE_BUFFER_HOURS = 6
SECONDS_PER_DAY = 86400


def ceil_div(numerator, denominator):
    return -(-numerator // denominator)


def floor_div(numerator, denominator):
    return numerator // denominator


def round_half_up(numerator, denominator):
    """Round (numerator / denominator) to nearest integer, ties away from zero
    (half up). Operands are non-negative integers here."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


# --------------------------------------------------------------------------
# premium_quote
# --------------------------------------------------------------------------
def premium_quote(trip_cost_cents, plan, covered_insured, cfar_opted):
    """Returns (base_premium_cents, premium_cents).

    base = ceil(trip_cost * base_rate_bps / 10000)
    senior loading applies if any COVERED insured age_at_departure >= senior_age_threshold
    cfar loading applies if cfar_opted
    each term ceil'd independently; premium = base + senior + cfar
    """
    base = ceil_div(trip_cost_cents * plan["base_rate_bps"], 10000)

    senior_present = any(
        it["age_at_departure"] >= plan["senior_age_threshold"]
        for it in covered_insured
    )
    senior_loading = ceil_div(base * plan["senior_loading_bps"], 10000) if senior_present else 0
    cfar_loading = ceil_div(base * plan["cfar_loading_bps"], 10000) if cfar_opted else 0

    premium = base + senior_loading + cfar_loading
    return base, premium


# --------------------------------------------------------------------------
# aggregate_limit_pin (at issuance)
# --------------------------------------------------------------------------
def cancellation_peril_cap(trip_cost_cents, plan):
    return floor_div(trip_cost_cents * plan["cancellation_limit_pct"], 100)


def aggregate_limit_pin(trip_cost_cents, plan):
    cancellation_cents = cancellation_peril_cap(trip_cost_cents, plan)
    return (
        cancellation_cents
        + plan["medical_limit_cents"]
        + plan["delay_limit_cents"]
        + plan["baggage_limit_cents"]
    )


# --------------------------------------------------------------------------
# preexisting_waiver_eligibility (at issuance)
# --------------------------------------------------------------------------
def days_between_floor(later_dt, earlier_dt):
    """Whole days from earlier to later, floored."""
    delta_seconds = (later_dt - earlier_dt).total_seconds()
    return math.floor(delta_seconds / SECONDS_PER_DAY)


def days_between_ceil(later_dt, earlier_dt):
    delta_seconds = (later_dt - earlier_dt).total_seconds()
    return math.ceil(delta_seconds / SECONDS_PER_DAY)


def preexisting_waiver_granted(issued_at_dt, initial_deposit_dt, plan, full_cost_insured):
    days_to_issue = days_between_floor(issued_at_dt, initial_deposit_dt)
    return (days_to_issue <= plan["waiver_window_days"]) and full_cost_insured


# --------------------------------------------------------------------------
# cancellation_reimbursement
# --------------------------------------------------------------------------
def cancellation_provisional(expenses, trip_cost_cents, plan, remaining_aggregate_cents):
    """Provisional (documented-loss basis): per PREPAID_TRIP line take
    min(documented_amount, prepaid_nonrefundable); sum; cap at peril cap and
    remaining aggregate. Ignores supplier refunds and CFAR percentage."""
    raw = 0
    for e in expenses:
        if e["category"] == "PREPAID_TRIP":
            raw += min(e["documented_amount_cents"], e["prepaid_nonrefundable_cents"])
    cap = cancellation_peril_cap(trip_cost_cents, plan)
    return min(raw, cap, remaining_aggregate_cents)


def cancellation_final(expenses, trip_cost_cents, plan, remaining_aggregate_cents, cancellation_reason):
    """Final (net-of-supplier-refund basis): per PREPAID_TRIP line take
    max(0, prepaid_nonrefundable - supplier_refund_received); sum; if CFAR,
    floor(raw * cfar_reimbursement_pct / 100); cap at peril cap and remaining."""
    raw = 0
    for e in expenses:
        if e["category"] == "PREPAID_TRIP":
            raw += max(0, e["prepaid_nonrefundable_cents"] - e["supplier_refund_received_cents"])
    if cancellation_reason == "CFAR":
        raw = floor_div(raw * plan["cfar_reimbursement_pct"], 100)
    cap = cancellation_peril_cap(trip_cost_cents, plan)
    return min(raw, cap, remaining_aggregate_cents)


# --------------------------------------------------------------------------
# medical_reimbursement
# --------------------------------------------------------------------------
def medical_final(expenses, plan, remaining_aggregate_cents):
    raw = 0
    for e in expenses:
        if e["category"] == "MEDICAL_BILL":
            raw += max(0, e["documented_amount_cents"] - e["supplier_refund_received_cents"])
    return min(raw, plan["medical_limit_cents"], remaining_aggregate_cents)


def medical_provisional(expenses, plan, remaining_aggregate_cents):
    """Provisional basis for MEDICAL: documented-loss basis ignoring supplier
    refunds. Mirrors the cancellation provisional/final split — provisional uses
    documented amounts only."""
    raw = 0
    for e in expenses:
        if e["category"] == "MEDICAL_BILL":
            raw += e["documented_amount_cents"]
    return min(raw, plan["medical_limit_cents"], remaining_aggregate_cents)


# --------------------------------------------------------------------------
# delay_reimbursement
# --------------------------------------------------------------------------
def delay_final(delay_hours, plan, remaining_aggregate_cents):
    blocks = floor_div(delay_hours, MIN_DELAY_HOURS)
    raw = blocks * plan["delay_block_cap_cents"]
    return min(raw, plan["delay_limit_cents"], remaining_aggregate_cents)


# --------------------------------------------------------------------------
# baggage_reimbursement (per-item rounding pinned BEFORE summation)
# --------------------------------------------------------------------------
def baggage_final(expenses, plan, remaining_aggregate_cents):
    total = 0
    for e in expenses:
        if e["category"] == "BAGGAGE_ITEM":
            depreciated = round_half_up(
                e["item_value_cents"] * (10000 - plan["baggage_depreciation_bps"]),
                10000,
            )
            covered = min(depreciated, plan["baggage_item_sublimit_cents"])
            total += covered
    return min(total, plan["baggage_limit_cents"], remaining_aggregate_cents)


def baggage_provisional(expenses, plan, remaining_aggregate_cents):
    """Provisional baggage estimate uses the same per-item depreciation+sublimit
    basis as the final figure (no supplier-refund / CFAR distinction for baggage)."""
    return baggage_final(expenses, plan, remaining_aggregate_cents)


# --------------------------------------------------------------------------
# premium_refund
# --------------------------------------------------------------------------
def refund_free_look(premium_cents):
    return premium_cents


def refund_short_rate(premium_cents, issued_at_dt, trip_end_at_dt, current_clock_dt):
    coverage_period_days = days_between_ceil(trip_end_at_dt, issued_at_dt)
    elapsed_days = days_between_floor(current_clock_dt, issued_at_dt)
    if coverage_period_days <= 0:
        unearned = 0
    else:
        unearned = floor_div(
            premium_cents * (coverage_period_days - elapsed_days),
            coverage_period_days,
        )
    return max(0, unearned - SHORT_RATE_ADMIN_FEE_CENTS)
