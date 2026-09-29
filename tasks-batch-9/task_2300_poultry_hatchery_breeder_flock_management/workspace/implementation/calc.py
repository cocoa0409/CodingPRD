"""Calculation rules (scaffold Table 3 / PRD §3).

Every monetary-style / precision-sensitive quantity is a Decimal and every
rounding step is ROUND_HALF_UP, per PRD §2.6.
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING

# ---- constants -------------------------------------------------------------
BASE_PHOTOPERIOD_HOURS = Decimal("8.0")
TARGET_FEED_G = Decimal("160.0")
SETTABLE_RATIO = Decimal("0.94")
CORRECTIVE_DERATE = Decimal("0.95")

SANITATION_AGE_PENALTY_DAYS = Decimal("0.75")
STORAGE_TEMP_BOUNDARY_C = Decimal("18.0")
WARM_FACTOR = Decimal("1.5")
COOL_FACTOR = Decimal("1.0")
UNSTORED_FACTOR = Decimal("2.0")
MAX_SETTABLE_AGE_DAYS = Decimal("10.00")

FREE_STORAGE_DAYS = Decimal("3")
HOUR_PER_STORAGE_DAY = Decimal("1.0")
PULL_WINDOW_EARLY_HOURS = 6
PULL_WINDOW_LATE_HOURS = 6
SETTER_TURNAROUND_HOURS = 12

TEMP_TOLERANCE_C = Decimal("0.30")
DEVIATION_OPEN_THRESHOLD_DH = Decimal("1.50")
DEVIATION_CLEAR_HOURS = Decimal("2.0")

BOX_SIZE = 100
TIER_A_MIN_PCT = Decimal("96.0")
TIER_B_MIN_PCT = Decimal("92.0")
TIER_C_MIN_PCT = Decimal("85.0")
TIER_A_RATE = Decimal("0.004")
TIER_B_RATE = Decimal("0.008")
TIER_C_RATE = Decimal("0.015")
TIER_D_RATE = Decimal("0.028")

EARLY_PENALTY_PER_H = Decimal("1.80")
LATE_PENALTY_PER_H = Decimal("2.40")
DEG_HOUR_WEIGHT = Decimal("3.00")
ENV_PENALTY_CAP = Decimal("25.00")
CULL_WEIGHT = Decimal("0.90")
FLAG_PENALTY = Decimal("4.00")

ROLLING_WINDOW_SETS = 3
HATCHABILITY_THRESHOLD_PCT = Decimal("82.0")

EARLY_HOLD_HOURS = 4
FARM_CYCLE_DAYS = 21
DELIVERY_TOLERANCE_DAYS = 2

SECONDS_PER_DAY = Decimal("86400")
SECONDS_PER_HOUR = Decimal("3600")

BREEDS = ("ROSS_308", "COBB_500", "HUBBARD_JA87")


# ---- rounding primitives ---------------------------------------------------
def dec(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


def rnd(value, places):
    q = Decimal(1).scaleb(-places)
    return dec(value).quantize(q, rounding=ROUND_HALF_UP)


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


def seconds_between(later, earlier):
    return dec((later - earlier).total_seconds())


# ---- flock_settable_forecast ----------------------------------------------
def step_lookup(steps, age_weeks, value_key, default):
    applicable = default
    for step in steps:
        if step["age_weeks"] <= age_weeks:
            applicable = dec(step[value_key])
        else:
            break
    return applicable


def age_weeks_of(hatch_date, clock_now):
    days = seconds_between(clock_now, hatch_date) / SECONDS_PER_DAY
    return floor_int(days / Decimal("7"))


def production_rate_for(age_weeks):
    if age_weeks < 21:
        return Decimal("0.0")
    if age_weeks <= 24:
        return Decimal("45.0")
    if age_weeks <= 30:
        return Decimal("82.0")
    if age_weeks <= 45:
        return Decimal("74.0")
    return Decimal("61.0")


def lighting_factor_for(photoperiod_hours):
    excess = dec(photoperiod_hours) - Decimal("11.0")
    if excess < 0:
        excess = Decimal("0")
    raw = Decimal("0.70") + Decimal("0.03") * excess
    if raw > Decimal("1.00"):
        raw = Decimal("1.00")
    return rnd(raw, 4)


def nutrition_factor_for(feed_grams):
    ratio = dec(feed_grams) / TARGET_FEED_G
    if ratio < Decimal("0.80"):
        ratio = Decimal("0.80")
    if ratio > Decimal("1.10"):
        ratio = Decimal("1.10")
    return rnd(ratio, 4)


def settable_forecast(hen_count, production_rate_pct, lighting_factor,
                      nutrition_factor, corrective_action_count):
    derate = CORRECTIVE_DERATE if corrective_action_count >= 1 else Decimal("1.0")
    product = (dec(hen_count)
               * (dec(production_rate_pct) / Decimal("100"))
               * dec(lighting_factor)
               * dec(nutrition_factor)
               * SETTABLE_RATIO
               * derate)
    return floor_int(product)


# ---- egg_lot_effective_age_days ------------------------------------------
def effective_age_days(collected_at, stored_at, storage_temp_c,
                       sanitation_cycle_count, clock_now):
    base_days = seconds_between(clock_now, collected_at) / SECONDS_PER_DAY
    if stored_at is None:
        factor = UNSTORED_FACTOR
    elif storage_temp_c is not None and dec(storage_temp_c) > STORAGE_TEMP_BOUNDARY_C:
        factor = WARM_FACTOR
    else:
        factor = COOL_FACTOR
    total = base_days * factor + SANITATION_AGE_PENALTY_DAYS * dec(sanitation_cycle_count)
    return rnd(total, 2)


# ---- incubation_pull_window ----------------------------------------------
def weighted_age_days(items):
    """items: iterable of (eggs_taken, effective_age_days_at_set) for ACTIVE draws."""
    numerator = Decimal("0")
    denominator = Decimal("0")
    for eggs, age in items:
        numerator += dec(eggs) * dec(age)
        denominator += dec(eggs)
    if denominator == 0:
        return None
    return rnd(numerator / denominator, 4)


def storage_delay_hours(weighted_age):
    excess = dec(weighted_age) - FREE_STORAGE_DAYS
    if excess < 0:
        excess = Decimal("0.0")
    hours = ceil_int(excess * HOUR_PER_STORAGE_DAY)
    return max(0, hours)


# ---- deviation_degree_hours ---------------------------------------------
def stage_for_hour(stages, elapsed_hours):
    elapsed = dec(elapsed_hours)
    for stage in stages:
        if dec(stage["from_hour"]) <= elapsed < dec(stage["to_hour"]):
            return stage
    if stages and elapsed >= dec(stages[-1]["to_hour"]):
        return stages[-1]
    return stages[0] if stages else None


def segment_degree_hours(prev_abs_deviation, span_hours):
    excess = dec(prev_abs_deviation) - TEMP_TOLERANCE_C
    if excess < 0:
        excess = Decimal("0.0")
    return rnd(excess * dec(span_hours), 3)


# ---- chick_yield_resolution ---------------------------------------------
def preliminary_yield_pct(hatched_count, sexing_cull_count):
    return rnd(dec(hatched_count - sexing_cull_count) / dec(hatched_count) * Decimal("100"), 2)


def vaccine_reject_rate(prelim_pct):
    prelim = dec(prelim_pct)
    if prelim >= TIER_A_MIN_PCT:
        return TIER_A_RATE
    if prelim >= TIER_B_MIN_PCT:
        return TIER_B_RATE
    if prelim >= TIER_C_MIN_PCT:
        return TIER_C_RATE
    return TIER_D_RATE


def vaccine_cull_count(hatched_count, sexing_cull_count, rate):
    return ceil_int(dec(hatched_count - sexing_cull_count) * dec(rate))


def final_yield_pct(saleable_count, hatched_count):
    return rnd(dec(saleable_count) / dec(hatched_count) * Decimal("100"), 2)


def box_count_for(saleable_count):
    return ceil_int(dec(saleable_count) / dec(BOX_SIZE))


# ---- chick_quality_score -------------------------------------------------
def quality_score(pull_class, pull_offset_hours, inherited_degree_hours,
                  cull_count, hatched_count, quality_flag, variant):
    early_penalty = Decimal("0.00")
    late_penalty = Decimal("0.00")
    if pull_class == "EARLY":
        early_penalty = rnd(EARLY_PENALTY_PER_H * abs(dec(pull_offset_hours)), 2)
    elif pull_class == "LATE":
        late_penalty = rnd(LATE_PENALTY_PER_H * dec(pull_offset_hours), 2)

    env_penalty = rnd(DEG_HOUR_WEIGHT * dec(inherited_degree_hours), 2)
    if env_penalty > ENV_PENALTY_CAP:
        env_penalty = ENV_PENALTY_CAP

    if variant == "FINAL":
        cull_penalty = rnd(CULL_WEIGHT * (dec(cull_count) / dec(hatched_count) * Decimal("100")), 2)
        flag_penalty = FLAG_PENALTY if quality_flag != "NONE" else Decimal("0.00")
    else:
        cull_penalty = Decimal("0.00")
        flag_penalty = Decimal("0.00")

    score = (Decimal("100.00") - early_penalty - late_penalty - env_penalty
             - cull_penalty - flag_penalty)
    return rnd(score, 2)


# ---- flock_hatchability_rolling -----------------------------------------
def pooled_pct(numerator, denominator):
    if denominator is None or dec(denominator) == 0:
        return None
    return rnd(dec(numerator) / dec(denominator) * Decimal("100"), 2)
