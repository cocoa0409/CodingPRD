"""Pure calculation routines (PRD Sections 2.8, 2.9, 3.3, 3.7, 3.8, 3.9)."""
from decimal import Decimal, ROUND_HALF_UP

import config

ZERO = Decimal(0)
ONE = Decimal(1)


def r_cents(value):
    """Round half-up to a whole cent and return an int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def r2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def r4(value):
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


# ------------------------------------------------------- facility score banding
def deficiency_level_for(score):
    if score >= config.DEFICIENCY_NONE_MIN_SCORE:
        return "NONE"
    if score >= config.DEFICIENCY_MINOR_MIN_SCORE:
        return "MINOR"
    return "MAJOR"


# ---------------------------------------------- expense allocation & settlement
def _club_lines(gross_by_category):
    """Per-category club line, rounded half-up per line before any summing."""
    lines = {}
    for cat in config.CATEGORY_ORDER:
        gross = Decimal(gross_by_category.get(cat, 0))
        lines[cat] = r_cents(gross * config.CLUB_SHARE_PCT[cat])
    return lines


def provisional_allocation(cap_cents, gross_by_category):
    """One aggregate bucket drained in CATEGORY_ORDER (housing, meals, travel,
    facility upkeep)."""
    lines = _club_lines(gross_by_category)
    remaining = int(cap_cents)
    allocated = 0
    for cat in config.CATEGORY_ORDER:
        take = lines[cat] if lines[cat] < remaining else remaining
        if take < 0:
            take = 0
        allocated += take
        remaining -= take
    total_lines = sum(lines[c] for c in config.CATEGORY_ORDER)
    return allocated, total_lines - allocated


def final_allocation(cap_cents, gross_by_category):
    """Pro-rata per-category sub-caps; no category may borrow from another."""
    lines = _club_lines(gross_by_category)
    final_lines = {}
    for cat in config.CATEGORY_ORDER:
        sub_cap = r_cents(
            Decimal(cap_cents) * config.CLUB_SHARE_PCT[cat] / config.SUM_SHARE_PCT)
        line = lines[cat]
        final_lines[cat] = line if line < sub_cap else sub_cap
    total_lines = sum(lines[c] for c in config.CATEGORY_ORDER)
    total_final = sum(final_lines[c] for c in config.CATEGORY_ORDER)
    return total_final, total_lines - total_final


# ------------------------------------------------------- signing pool arithmetic
def overage_tax_on(overage):
    """Marginal tiered tax carried as an exact decimal (no rounding here)."""
    amount = Decimal(overage)
    if amount <= 0:
        return ZERO
    tier1 = amount if amount < config.POOL_TIER_1_CEILING_CENTS else config.POOL_TIER_1_CEILING_CENTS
    span2 = amount - config.POOL_TIER_1_CEILING_CENTS
    if span2 < 0:
        span2 = ZERO
    band2 = config.POOL_TIER_2_CEILING_CENTS - config.POOL_TIER_1_CEILING_CENTS
    tier2 = span2 if span2 < band2 else band2
    tier3 = amount - config.POOL_TIER_2_CEILING_CENTS
    if tier3 < 0:
        tier3 = ZERO
    return (tier1 * config.TIER_1_TAX_RATE
            + tier2 * config.TIER_2_TAX_RATE
            + tier3 * config.TIER_3_TAX_RATE)


def signing_charge(base_cents, trade_cents, forfeited_cents, allocated_cents,
                   bonus_cents):
    """The four ordered steps of PRD Section 3.9.  Returns a result dict."""
    # Step 1 - snapshot the pool *before* any forfeit this approval imposes.
    effective_before = base_cents + trade_cents - forfeited_cents
    prior_overage = allocated_cents - effective_before
    if prior_overage < 0:
        prior_overage = 0
    new_allocated = allocated_cents + bonus_cents
    total_overage = new_allocated - effective_before
    if total_overage < 0:
        total_overage = 0

    # Step 2 - marginal tax, rounded once at the subtraction.
    tax = r_cents(overage_tax_on(total_overage) - overage_tax_on(prior_overage))

    # Step 3 - tier-3 forfeit, only after the tax has been computed.
    breach = (total_overage > int(config.POOL_TIER_2_CEILING_CENTS)
              and prior_overage <= int(config.POOL_TIER_2_CEILING_CENTS))
    forfeited_after = forfeited_cents + (config.TIER3_FORFEIT_CENTS if breach else 0)

    # Step 4 - recompute the ledger with the post-forfeit figure.
    effective_after = base_cents + trade_cents - forfeited_after
    return {
        "overage_tax_cents": tax,
        "pool_charge_cents": bonus_cents,
        "tier3_breach": breach,
        "forfeited_cents": forfeited_after,
        "allocated_cents": new_allocated,
        "effective_pool_cents": effective_after,
        "remaining_cents": effective_after - new_allocated,
        "hard_capped": new_allocated > effective_after,
    }


# ------------------------------------------------------------------- late fees
def late_fee_cents(days_late):
    if days_late <= 0:
        return 0
    seg1 = days_late if days_late < config.LATE_FEE_TIER_1_DAYS else config.LATE_FEE_TIER_1_DAYS
    seg2 = days_late - config.LATE_FEE_TIER_1_DAYS
    if seg2 < 0:
        seg2 = 0
    span2 = config.LATE_FEE_TIER_2_DAYS - config.LATE_FEE_TIER_1_DAYS
    if seg2 > span2:
        seg2 = span2
    seg3 = days_late - config.LATE_FEE_TIER_2_DAYS
    if seg3 < 0:
        seg3 = 0
    return (config.LATE_FEE_TIER_1_PER_DAY * seg1
            + config.LATE_FEE_TIER_2_PER_DAY * seg2
            + config.LATE_FEE_TIER_3_PER_DAY * seg3)


# --------------------------------------------------------------------- workload
def outing_contribution(pitches, innings, minutes, level):
    raw = (config.W_PITCHES * Decimal(pitches) / config.PITCH_DIVISOR
           + config.W_INNINGS * Decimal(innings) / config.INNINGS_DIVISOR
           + config.W_INTENSITY * Decimal(minutes) / config.INTENSITY_DIVISOR)
    return raw * config.LEVEL_WORKLOAD_MULTIPLIER[level]


def cap_index(value):
    rounded = r2(value)
    return rounded if rounded < config.WORKLOAD_INDEX_CEILING else config.WORKLOAD_INDEX_CEILING


def readiness_score(completed, module_count, projected_index, weekly_limit,
                    service_days):
    module_ratio = Decimal(completed) / Decimal(module_count) if module_count else ZERO
    denominator = Decimal(weekly_limit) * Decimal(config.PRESSURE_HORIZON_WEEKS)
    if denominator <= 0:
        pressure = ONE
    else:
        pressure = Decimal(projected_index) / denominator
        if pressure > ONE:
            pressure = ONE
    headroom = ONE - pressure
    if headroom < 0:
        headroom = ZERO
    service_ratio = Decimal(service_days) / Decimal(config.PROMOTION_MIN_SERVICE_DAYS)
    if service_ratio > ONE:
        service_ratio = ONE
    return r4(config.W_MODULE_COMPLETION * module_ratio
              + config.W_WORKLOAD_HEADROOM * headroom
              + config.W_SERVICE_TIME * service_ratio)
