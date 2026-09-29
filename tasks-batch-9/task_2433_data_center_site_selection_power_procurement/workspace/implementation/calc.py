"""Pure calculation kernels.

One function (or small group) per named calculation in the specification. None of
these touch the store; `derive.py` wires them to persisted rows.
"""

from decimal import Decimal

import constants as K
from rounding import dec, q2, q3, q4
from timeutil import days_between, parse_dt, plus_days

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")


# --------------------------------------------------------------------------- #
# site_screening_score
# --------------------------------------------------------------------------- #
def hazard_tier(seismic, flood, wind):
    top = max(dec(seismic), dec(flood), dec(wind))
    if top >= K.HAZARD_SEVERE_THRESHOLD:
        return "SEVERE"
    if top >= K.HAZARD_MODERATE_THRESHOLD:
        return "MODERATE"
    return "LOW"


def workforce_ratio(craft_labor_supply_index, construction_peak_headcount):
    return q4(dec(craft_labor_supply_index) / dec(construction_peak_headcount))


def screening_score(
    transmission_headroom_mw,
    target_load_mw,
    fiber_route_count,
    annual_water_demand_mgal,
    water_headroom_mgal,
    workforce_availability_ratio,
    wage_premium_pct,
    gross_acres,
    tier,
):
    """Weighted score out of 100; components are summed at full precision and
    only the final score is rounded (2dp)."""
    power = K.WEIGHT_POWER * min(
        ONE, dec(transmission_headroom_mw) / dec(target_load_mw)
    )
    fiber = K.WEIGHT_FIBER * min(ONE, dec(fiber_route_count) / K.MIN_FIBER_ROUTES)

    demand = dec(annual_water_demand_mgal)
    if demand == 0:
        water = K.WEIGHT_WATER
    else:
        water = K.WEIGHT_WATER * max(
            ZERO, min(ONE, dec(water_headroom_mgal) / demand)
        )

    workforce = K.WEIGHT_WORKFORCE * min(ONE, dec(workforce_availability_ratio))
    if dec(wage_premium_pct) > K.WAGE_PREMIUM_THRESHOLD:
        workforce = workforce * K.WAGE_PENALTY_FACTOR

    land = K.WEIGHT_LAND * min(ONE, dec(gross_acres) / K.MIN_SITE_ACRES)

    raw = power + fiber + water + workforce + land - K.HAZARD_PENALTY[tier]
    return q2(max(ZERO, min(HUNDRED, raw)))


# --------------------------------------------------------------------------- #
# load_study_peak_load
# --------------------------------------------------------------------------- #
def load_study_figures(
    it_load_mw,
    cooling_load_mw,
    ancillary_load_mw,
    diversity_factor,
    total_transmission_capacity_mw,
    network_upgrade_rate_usd_per_mw,
    site_hazard_tier,
):
    it = dec(it_load_mw)
    cooling = dec(cooling_load_mw)
    ancillary = dec(ancillary_load_mw)
    factor = dec(diversity_factor)

    # nameplate_stacked: plain arithmetic sum, diversity and cooling floor ignored.
    nameplate = q3(it + cooling + ancillary)
    # diversified_coincident: cooling never diversifies below the cooling floor.
    diversified = q3(
        it * factor + cooling * max(factor, K.COOLING_FLOOR_FACTOR) + ancillary
    )

    trigger = q3(dec(total_transmission_capacity_mw) * K.UPGRADE_TRIGGER_RATIO)
    upgrade_required = diversified > trigger  # strict: equality does not trigger

    if not upgrade_required:
        cost = q2(ZERO)
    else:
        uplift = K.HAZARD_UPLIFT.get(site_hazard_tier, Decimal("0.00"))
        cost = q2(diversified * dec(network_upgrade_rate_usd_per_mw) * (ONE + uplift))

    return nameplate, diversified, upgrade_required, cost


# --------------------------------------------------------------------------- #
# transmission_overlap_capacity
# --------------------------------------------------------------------------- #
def buffered_overlap(a_start, a_end, b_start, b_end, buffer_days):
    """Closed intervals with the commissioning buffer applied to BOTH ends of
    BOTH windows under test."""
    a1 = parse_dt(a_start)
    a2 = parse_dt(a_end)
    b1 = parse_dt(b_start)
    b2 = parse_dt(b_end)
    buffer_days = int(buffer_days or 0)
    return a1 <= plus_days(b2, buffer_days) and b1 <= plus_days(a2, buffer_days)


def half_open_overlap(a_start, a_end, b_start, b_end):
    """[start, end) overlap: abutting windows do not collide and no buffer applies."""
    a1 = parse_dt(a_start)
    a2 = parse_dt(a_end)
    b1 = parse_dt(b_start)
    b2 = parse_dt(b_end)
    return a1 < b2 and b1 < a2


# --------------------------------------------------------------------------- #
# energization_delay_exposure
# --------------------------------------------------------------------------- #
def delay_days(committed_energization_date, required_energization_date):
    return days_between(
        parse_dt(committed_energization_date), parse_dt(required_energization_date)
    )


def delay_exposure(days, requested_mw):
    if days <= 0:
        return q2(ZERO)
    return q2(Decimal(int(days)) * K.DELAY_PENALTY_USD_PER_DAY_PER_MW * dec(requested_mw))


# --------------------------------------------------------------------------- #
# incentive_npv
# --------------------------------------------------------------------------- #
def sales_tax_tier_rate(capex_commitment_usd):
    capex = dec(capex_commitment_usd)
    if capex < K.TIER_MID_FLOOR_USD:
        return K.SALES_TAX_TIER_LOW
    if capex < K.TIER_HIGH_FLOOR_USD:
        return K.SALES_TAX_TIER_MID
    return K.SALES_TAX_TIER_HIGH


def incentive_money(
    capex_commitment_usd,
    sales_tax_exemption_pct,
    abatement_years,
    abatement_pct,
    jobs_commitment,
):
    capex = dec(capex_commitment_usd)
    rate = sales_tax_tier_rate(capex)
    sales_tax = q2(capex * K.EQUIPMENT_SHARE * rate * dec(sales_tax_exemption_pct))

    annual_base = capex * K.ASSESSED_RATIO * K.MILL_RATE * dec(abatement_pct)
    # Rounding order is pinned: each year is rounded to cents BEFORE summation.
    abatement = Decimal("0.00")
    discount = ONE + K.DISCOUNT_RATE
    for year in range(1, int(abatement_years) + 1):
        abatement += q2(annual_base / (discount ** year))
    abatement = q2(abatement)

    npv = q2(sales_tax + abatement)
    share = (
        K.CLAWBACK_SHARE_HIGH_JOBS
        if int(jobs_commitment) >= K.JOBS_THRESHOLD
        else K.CLAWBACK_SHARE_LOW_JOBS
    )
    return sales_tax, abatement, npv, q2(npv * share)


# --------------------------------------------------------------------------- #
# zoning_mitigation_and_escrow
# --------------------------------------------------------------------------- #
def weighted_opposition(objection_types):
    total = ZERO
    for kind in objection_types:
        total += K.OBJECTION_WEIGHT[kind]
    return q2(total)


def noise_excess(projected_noise_dba, noise_limit_dba):
    diff = dec(projected_noise_dba) - dec(noise_limit_dba)
    return diff if diff > 0 else ZERO


def required_mitigation_tier(noise_excess_dba, weighted_opposition_score):
    excess = dec(noise_excess_dba)
    score = dec(weighted_opposition_score)
    if excess >= 10 or score >= 12:
        return "FULL_ENCLOSURE"
    if excess >= 5 or score >= 6:
        return "BERM_AND_SCREENING"
    if excess > 0 or score >= 3:
        return "BERM"
    return "NONE"


def mitigation_cost(tier, noise_excess_dba):
    return q2(K.TIER_BASE[tier] + dec(noise_excess_dba) * K.DBA_UNIT_COST)


def conditions_escrow(mitigation_cost_usd):
    cost = dec(mitigation_cost_usd)
    if cost == 0:
        pct = Decimal("0.00")
    elif cost < K.ESCROW_MID_FLOOR_USD:
        pct = K.ESCROW_PCT_SMALL
    elif cost < K.ESCROW_HIGH_FLOOR_USD:
        pct = K.ESCROW_PCT_MID
    else:
        pct = K.ESCROW_PCT_LARGE
    return q2(cost * pct)


# --------------------------------------------------------------------------- #
# ppa_credited_coverage
# --------------------------------------------------------------------------- #
def ppa_credited_coverage(
    technology, matching_mode, annual_generation_mwh, hourly_matched_mwh
):
    if matching_mode == "ANNUAL_VOLUMETRIC":
        return q3(dec(annual_generation_mwh) * (ONE - K.CURTAILMENT[technology]))
    return q3(dec(hourly_matched_mwh) * K.HOURLY_DELIVERABILITY)


def annual_cost(annual_generation_mwh, strike_price_usd_per_mwh):
    return q2(dec(annual_generation_mwh) * dec(strike_price_usd_per_mwh))


def program_annual_load(target_load_mw):
    return q3(dec(target_load_mw) * K.HOURS_PER_YEAR * K.PROGRAM_LOAD_FACTOR)


def coverage_pct(credited_total, program_annual_load_mwh):
    denominator = dec(program_annual_load_mwh)
    if denominator == 0:
        return q2(ZERO)
    return q2(HUNDRED * dec(credited_total) / denominator)


# --------------------------------------------------------------------------- #
# option_premium_ledger / land_control_rollup
# --------------------------------------------------------------------------- #
def premium_credited(option_premium_usd, premium_credit_pct):
    return q2(dec(option_premium_usd) * dec(premium_credit_pct))


def net_purchase(purchase_price_usd, premium_credited_usd):
    return q2(dec(purchase_price_usd) - dec(premium_credited_usd))


def land_control(controlled_acres, gross_acres):
    gross = dec(gross_acres)
    if gross == 0:
        pct = q2(ZERO)
    else:
        pct = q2(min(HUNDRED, HUNDRED * dec(controlled_acres) / gross))
    if pct >= HUNDRED:
        status = "FULL"
    elif pct == 0:
        status = "NONE"
    else:
        status = "PARTIAL"
    return pct, status


# --------------------------------------------------------------------------- #
# water_headroom_and_feasibility
# --------------------------------------------------------------------------- #
def effective_supply(annual_permitted_mgal, drought_stage):
    return q3(
        dec(annual_permitted_mgal) * (ONE - K.STAGE_CURTAILMENT[drought_stage])
    )
