"""Every calculation rule in the PRD, with the exact constants and rounding."""

from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal("0")


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=2):
    """Round half up -- a value on the boundary rounds away from zero."""
    return D(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def ceil_div(numerator, denominator):
    numerator = int(numerator)
    denominator = int(denominator)
    return -((-numerator) // denominator)


# --------------------------------------------------------------------------- #
# constants
# --------------------------------------------------------------------------- #
SECONDS_PER_DAY = D(86400)
GRAMS_PER_TON = D(1000000)

COLOR_WEAR_FACTOR = {"FLINT": D("1.00"), "AMBER": D("1.15"), "GREEN": D("1.30")}
OVER_PULL_WEIGHT = D("2.0")
CULLET_STRESS_WEIGHT = D("0.8")
CULLET_STRESS_FLOOR_PCT = D("45.00")

SWAP_BASE_MINUTES = D("60")
FOREIGN_FAMILY_FACTOR = D("1.5")
CHANGEOVER_CAP_MINUTES = 240

UNITS_PER_PALLET = {"EURO_1200x800": 1800, "GMA_1200x1000": 2100}
CREDIT_FACTOR = D("0.5")

TIER_B_FLOOR = D("100000.00")
TIER_C_FLOOR = D("500000.00")
TIER_RESERVE_RATE = {"TIER_A": D("0.05"), "TIER_B": D("0.09"), "TIER_C": D("0.14")}
TIER_REBATE_RATE = {"TIER_A": D("0.20"), "TIER_B": D("0.30"), "TIER_C": D("0.40")}
RISK_RATE_PER_POINT = D("0.0009")

THINNESS_REF = D("0.36")
THINNESS_WEIGHT = D(8)
SPEED_DIVISOR = D(250)
SPEED_WEIGHT = D(12)
HISTORY_WEIGHT = D(6)
THIN_WALL_MM = D("1.60")
THIN_WALL_PENALTY = D(8)
RISK_SIGNOFF_CAP = D("55.00")
RISK_DELTA_CAP = D("30.00")

BASE_DAYS = 45
CAVITY_STEP_DAYS = 5
CAVITIES_PER_STEP = 4
REVISION_DAYS = 7
SUPERSEDE_CREDIT_DAYS = 10
LEAD_TIME_FLOOR_DAYS = 30

MAJOR_PPM_LIMIT = D("2500.0")
COMBINED_PPM_LIMIT = D("9000.0")

BASE_AGING_DAYS = 3
THIN_WALL_AGING_DAYS = 2
ADOPTED_PROGRAM_AGING_DAYS = 3

REBUILD_DUE_PCT = D("5.00")
RESTRICTED_PCT = D("15.00")

WATCH_FRACTION = D("0.5")

HISTORY_TERM = {"GOOD": D(0), "WATCH": D(1), "CRITICAL": D(2)}

TRANSITION_LOOKBACK_DAYS = 7


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def window_days(start, end):
    """Fractional days between two instants; a 36-hour window is 1.5 days."""
    return D(repr((end - start).total_seconds())) / SECONDS_PER_DAY


def tons_from_units(units, unit_weight_g):
    return rhu(D(units) * D(unit_weight_g) / GRAMS_PER_TON, 2)


# --------------------------------------------------------------------------- #
# refractory wear (nominal / stress_adjusted)
# --------------------------------------------------------------------------- #
def cullet_stress_factor(cullet_ratio_pct):
    excess = D(cullet_ratio_pct) - CULLET_STRESS_FLOOR_PCT
    if excess < ZERO:
        excess = ZERO
    return rhu(excess / D(100), 4)


def base_wear_units(pull_tpd, days, color):
    return D(pull_tpd) * D(days) * COLOR_WEAR_FACTOR[color]


def stress_multiplier(planned_pull_tpd, design_pull_tpd, stress_factor):
    over_pull = (D(planned_pull_tpd) - D(design_pull_tpd)) / D(design_pull_tpd)
    if over_pull < ZERO:
        over_pull = ZERO
    return D(1) + OVER_PULL_WEIGHT * over_pull + CULLET_STRESS_WEIGHT * D(stress_factor)


def refractory_nominal(pull_tpd, days, color):
    return rhu(base_wear_units(pull_tpd, days, color), 2)


def refractory_stress_adjusted(pull_tpd, days, color, design_pull_tpd, stress_factor):
    base = base_wear_units(pull_tpd, days, color)
    return rhu(base * stress_multiplier(pull_tpd, design_pull_tpd, stress_factor), 2)


def remaining_pct(consumed_units, total_units):
    pct = rhu(D(100) * (D(1) - D(consumed_units) / D(total_units)), 2)
    if pct < D("0.00"):
        pct = D("0.00")
    if pct > D("100.00"):
        pct = D("100.00")
    return pct


# --------------------------------------------------------------------------- #
# changeover minutes
# --------------------------------------------------------------------------- #
def changeover_minutes(mold_family, machine_family, set_cavities, design_cavities, condition_score):
    family_factor = FOREIGN_FAMILY_FACTOR if mold_family != machine_family else D("1.0")
    swap_minutes = SWAP_BASE_MINUTES * family_factor
    cavity_delta = abs(int(set_cavities) - int(design_cavities))
    if cavity_delta == 0:
        cavity_tier = D(0)
    elif cavity_delta <= 2:
        cavity_tier = D(15)
    elif cavity_delta <= 5:
        cavity_tier = D(35)
    else:
        cavity_tier = D(60)
    score = int(condition_score)
    if score >= 85:
        condition_pen = D(0)
    elif score >= 71:
        condition_pen = D(10)
    else:
        condition_pen = D(25)
    total = int(rhu(swap_minutes + max(cavity_tier, condition_pen), 0))
    return min(CHANGEOVER_CAP_MINUTES, total)


# --------------------------------------------------------------------------- #
# breakage risk index / lead time
# --------------------------------------------------------------------------- #
def breakage_risk_index(nominal_weight_g, capacity_ml, min_wall_thickness_mm, target_line_speed_bpm, quality_standing):
    thinness = THINNESS_REF - (D(nominal_weight_g) / D(capacity_ml))
    if thinness < ZERO:
        thinness = ZERO
    thinness = thinness * D(100)
    speed_factor = D(target_line_speed_bpm) / SPEED_DIVISOR
    history = HISTORY_TERM[quality_standing]
    wall_penalty = THIN_WALL_PENALTY if D(min_wall_thickness_mm) < THIN_WALL_MM else ZERO
    raw = (
        THINNESS_WEIGHT * thinness
        + SPEED_WEIGHT * speed_factor
        + HISTORY_WEIGHT * history
        + wall_penalty
    )
    return min(D("100.00"), rhu(raw, 2))


def design_lead_time_days(cavity_count, revision_count, risk_index, supersedes):
    cavity_term = CAVITY_STEP_DAYS * ceil_div(cavity_count, CAVITIES_PER_STEP)
    revision_term = REVISION_DAYS * int(revision_count)
    index = D(risk_index)
    if index <= D("30.00"):
        risk_term = 0
    elif index <= D("45.00"):
        risk_term = 10
    else:
        risk_term = 25
    supersede_credit = SUPERSEDE_CREDIT_DAYS if supersedes else 0
    return max(
        LEAD_TIME_FLOOR_DAYS,
        BASE_DAYS + cavity_term + revision_term + risk_term - supersede_credit,
    )


# --------------------------------------------------------------------------- #
# lightweighting economics
# --------------------------------------------------------------------------- #
def savings_tier(gross_savings_usd):
    gross = D(gross_savings_usd)
    if gross < TIER_B_FLOOR:
        return "TIER_A"
    if gross < TIER_C_FLOOR:
        return "TIER_B"
    return "TIER_C"


def lightweighting_economics(baseline_weight_g, target_weight_g, annual_volume_units,
                             price_per_kg, baseline_risk_index, target_risk_index):
    weight_saved_g = rhu(D(baseline_weight_g) - D(target_weight_g), 2)
    saved_kg = weight_saved_g * D(annual_volume_units) / D(1000)
    gross = rhu(saved_kg * D(price_per_kg), 2)
    tier = savings_tier(gross)
    risk_delta = rhu(D(target_risk_index) - D(baseline_risk_index), 2)
    reserve_rate = rhu(TIER_RESERVE_RATE[tier] + RISK_RATE_PER_POINT * risk_delta, 5)
    reserve = rhu(gross * reserve_rate, 2)
    net = rhu(gross - reserve, 2)
    rebate = rhu(net * TIER_REBATE_RATE[tier], 2)
    return {
        "weight_saved_g": weight_saved_g,
        "gross_savings_usd": gross,
        "savings_tier": tier,
        "breakage_risk_delta": risk_delta,
        "risk_reserve_usd": reserve,
        "net_savings_usd": net,
        "customer_rebate_usd": rebate,
    }


# --------------------------------------------------------------------------- #
# pull pool
# --------------------------------------------------------------------------- #
def pull_pool_tons(target_pull_tpd, campaign_days):
    return rhu(D(target_pull_tpd) * D(campaign_days), 2)


def available_pull_tons(pool_tons, melt_tons_charged, reserved_pull_tons):
    return rhu(D(pool_tons) - D(melt_tons_charged) - D(reserved_pull_tons), 2)


def reserved_melt_tons(planned_pull_tpd, job_days):
    return rhu(D(planned_pull_tpd) * D(job_days), 2)


# --------------------------------------------------------------------------- #
# lot ppm / disposition
# --------------------------------------------------------------------------- #
def ppm(rejected, packed_units):
    if int(packed_units) == 0:
        return D("0.0")
    return rhu(D(1000000) * D(rejected) / D(packed_units), 1)


def lot_disposition(has_critical, major_ppm, minor_ppm):
    if has_critical:
        return "SCRAPPED"
    if D(major_ppm) >= MAJOR_PPM_LIMIT:
        return "QUARANTINED"
    if D(major_ppm) + D(minor_ppm) >= COMBINED_PPM_LIMIT:
        return "QUARANTINED"
    return "RELEASED"


# --------------------------------------------------------------------------- #
# complaint credit / customer standing
# --------------------------------------------------------------------------- #
def breakage_ppm(affected_units, net_packed_units):
    if int(net_packed_units) == 0:
        return D("0.0")
    return rhu(D(1000000) * D(affected_units) / D(net_packed_units), 1)


def complaint_credit(palletization_standard, affected_units, container_price_usd,
                     complaint_breakage_ppm, complaint_ppm_threshold):
    units_per_pallet = UNITS_PER_PALLET[palletization_standard]
    affected_pallets = ceil_div(affected_units, units_per_pallet)
    severity_share = rhu(D(complaint_breakage_ppm) / D(complaint_ppm_threshold), 4)
    if severity_share > D("1.0000"):
        severity_share = D("1.0000")
    per_pallet = rhu(
        D(units_per_pallet) * D(container_price_usd) * severity_share * CREDIT_FACTOR, 2
    )
    credit = rhu(per_pallet * D(affected_pallets), 2)
    return affected_pallets, credit


def weighted_breakage_ppm(credited):
    """credited: iterable of (breakage_ppm, affected_units) in created_at ASC order."""
    numerator = ZERO
    denominator = 0
    for value, units in credited:
        numerator += D(value) * D(units)
        denominator += int(units)
    if denominator == 0:
        return D("0.00")
    return rhu(numerator / D(denominator), 2)


def quality_standing(weighted_ppm, threshold):
    weighted = D(weighted_ppm)
    limit = D(threshold)
    if weighted > limit:
        return "CRITICAL"
    if weighted > WATCH_FRACTION * limit:
        return "WATCH"
    return "GOOD"


# --------------------------------------------------------------------------- #
# yields
# --------------------------------------------------------------------------- #
def provisional_yield_pct(gross_packed_tons, reserved_tons):
    if D(reserved_tons) == ZERO:
        return D("0.00")
    return rhu(D(100) * D(gross_packed_tons) / D(reserved_tons), 2)


def final_yield_pct(net_packed_tons, reserved_tons, attributed_transition_tons):
    denominator = D(reserved_tons) + D(attributed_transition_tons)
    if denominator == ZERO:
        return D("0.00")
    return rhu(D(100) * D(net_packed_tons) / denominator, 2)
