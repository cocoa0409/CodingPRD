"""All eleven pinned calculations (PRD section 2.5 and section 3).

Money is integer cents; rates are integer basis points. Every division is an
exact rational rounded half-up (half away from zero) at the pinned step only.
"""

from decimal import ROUND_HALF_UP, Decimal, localcontext

import config


def round_half_up(numerator, denominator):
    """Exact rational rounding, half away from zero, integer in / integer out."""
    if denominator == 0:
        raise ZeroDivisionError("denominator must be non-zero")
    with localcontext() as ctx:
        ctx.prec = 80
        quotient = Decimal(int(numerator)) / Decimal(int(denominator))
        return int(quotient.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def scale_bps(amount, bps):
    """round_half_up(amount * bps / 10000)."""
    return round_half_up(int(amount) * int(bps), config.BPS_DENOMINATOR)


# ------------------------------------------------------------------ earn-out


def fee_bps_for(net_collections_cents):
    if net_collections_cents < config.FEE_TIER_1_CEILING_CENTS:
        return config.FEE_TIER_1_BPS
    if net_collections_cents < config.FEE_TIER_2_CEILING_CENTS:
        return config.FEE_TIER_2_BPS
    return config.FEE_TIER_3_BPS


def multiple_bps_for(growth_bps):
    if growth_bps < 0:
        return config.MULTIPLE_TIER_0_BPS
    if growth_bps < config.GROWTH_TIER_1_BPS:
        return config.MULTIPLE_TIER_1_BPS
    if growth_bps < config.GROWTH_TIER_2_BPS:
        return config.MULTIPLE_TIER_2_BPS
    return config.MULTIPLE_TIER_3_BPS


def earnout_payout(variant, nc_in, ex_in, baseline_ebitda_cents, days_elapsed=None):
    """The eight pinned steps of calculations.earnout_payout.

    Returns a dict of every intermediate the tranche must persist.
    """
    if variant == "PROVISIONAL":
        # Step 1 / 2: annualise both inputs against the elapsed days.
        net_collections = round_half_up(nc_in * config.DAYS_PER_YEAR, days_elapsed)
        expenses = round_half_up(ex_in * config.DAYS_PER_YEAR, days_elapsed)
        lag_holdback = 0
    else:
        # Step 1: withhold the lag basis points, then net them out. Step 2: verbatim.
        lag_holdback = scale_bps(nc_in, config.LAG_HOLDBACK_BPS)
        net_collections = nc_in - lag_holdback
        expenses = ex_in

    # Step 3 / 4: management fee tier, then the fee itself.
    fee_bps = fee_bps_for(net_collections)
    management_fee = scale_bps(net_collections, fee_bps)

    # Step 5: exact subtraction, no rounding.
    adjusted_ebitda = net_collections - expenses - management_fee

    # Step 6: growth in basis points against the deal baseline.
    growth_bps = round_half_up(
        (adjusted_ebitda - baseline_ebitda_cents) * config.BPS_DENOMINATOR,
        baseline_ebitda_cents,
    )

    # Step 7 / 8: multiple tier and the floored payout.
    multiple_bps = multiple_bps_for(growth_bps)
    raw_payout = scale_bps(adjusted_ebitda - baseline_ebitda_cents, multiple_bps)
    payout = max(0, raw_payout)

    return {
        "variant_applied": variant,
        "net_collections_cents": net_collections,
        "expenses_cents": expenses,
        "lag_holdback_cents": lag_holdback,
        "management_fee_cents": management_fee,
        "adjusted_ebitda_cents": adjusted_ebitda,
        "growth_bps": growth_bps,
        "multiple_bps": multiple_bps,
        "payout_cents": payout,
    }


# ------------------------------------------------------------- compensation


def doctor_compensation(comp_model, monthly_collections, base_salary_monthly_cents,
                        collections_pct_bps):
    """calculations.doctor_compensation — two variants with different rounding shapes."""
    if comp_model == "MONTHLY_MIN_GUARANTEE":
        total = 0
        for month_collections in monthly_collections:
            pct_month = scale_bps(month_collections, collections_pct_bps)
            total += max(base_salary_monthly_cents, pct_month)
        return total
    annual_collections = sum(monthly_collections)
    pct_annual = scale_bps(annual_collections, collections_pct_bps)
    return max(base_salary_monthly_cents * config.COMP_MONTHS, pct_annual)


def comp_cap_cents(legacy_annual_comp_cents):
    """The uplift ceiling: legacy * (10000 + MAX_COMP_UPLIFT_BPS) / 10000."""
    return legacy_annual_comp_cents * (
        config.BPS_DENOMINATOR + config.MAX_COMP_UPLIFT_BPS
    )


def comp_cap_exceeded(harmonized_cents, legacy_annual_comp_cents):
    return harmonized_cents * config.BPS_DENOMINATOR > comp_cap_cents(
        legacy_annual_comp_cents
    )


# ------------------------------------------------------------------ fee schedule


def fee_line_impact(legacy_allowed_cents, dso_allowed_cents, annual_volume):
    """One rounding per line: round_half_up(delta * volume * blend / 10000)."""
    delta = dso_allowed_cents - legacy_allowed_cents
    return round_half_up(
        delta * annual_volume * config.BLEND_FACTOR_BPS, config.BPS_DENOMINATOR
    )


def erosion_is_material(blended_impact_cents):
    return blended_impact_cents <= config.MATERIAL_EROSION_THRESHOLD_CENTS


# ------------------------------------------------------------------ migration


def validation_error_rate_bps(quarantined_count, records_total):
    return round_half_up(quarantined_count * config.BPS_DENOMINATOR, records_total)


# ------------------------------------------------------------------ procurement


def gross_savings(baseline_annual_spend_cents, formulary_annual_spend_cents):
    return scale_bps(
        baseline_annual_spend_cents - formulary_annual_spend_cents,
        config.REALIZATION_BPS,
    )


def exception_incremental_cost(preferred_unit_cents, formulary_unit_cents, annual_qty):
    """Exact integer product — no rounding step exists here."""
    return (preferred_unit_cents - formulary_unit_cents) * annual_qty


# ------------------------------------------------------------------ quality


def clinical_quality_score(charts_sampled, charts_with_findings, treatment_plan_overrides):
    """Four independent roundings, then a floored score."""
    finding_rate_bps = round_half_up(
        charts_with_findings * config.BPS_DENOMINATOR, charts_sampled
    )
    override_rate_bps = round_half_up(
        treatment_plan_overrides * config.BPS_DENOMINATOR, charts_sampled
    )
    finding_penalty = scale_bps(finding_rate_bps, config.W_FINDING_BPS)
    override_penalty = scale_bps(override_rate_bps, config.W_OVERRIDE_BPS)
    score_bps = max(0, config.FULL_SCORE_BPS - finding_penalty - override_penalty)
    return {
        "finding_rate_bps": finding_rate_bps,
        "override_rate_bps": override_rate_bps,
        "score_bps": score_bps,
    }
