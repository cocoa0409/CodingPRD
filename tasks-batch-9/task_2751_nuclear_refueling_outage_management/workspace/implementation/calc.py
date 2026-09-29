"""Calculation rules (PRD 3 / SCAFFOLD 1.3).

Every money, dose, hour, percent and score value is a Decimal carried to two
decimal places with ROUND_HALF_UP, unless a rule pins something different.
"""
from decimal import Decimal, ROUND_HALF_UP

D = Decimal
ZERO2 = D("0.00")

# --- work_order_priority_score ------------------------------------------------
SAFETY_WEIGHT_BY_TYPE = {"MAINTENANCE": D(20), "MODIFICATION": D(35), "INSPECTION": D(30)}
SF_BONUS = D(25)
REGULATORY_BONUS = D(20)
DURATION_PRESSURE_MULTIPLIER = D(300)
DURATION_PRESSURE_CAP = D(30)
DOSE_PENALTY_DIVISOR = D(100)
DOSE_PENALTY_CAP = D(15)
PRIORITY_CRITICAL_MIN = D(75)
PRIORITY_HIGH_MIN = D(45)

# --- rwp_committed_dose -------------------------------------------------------
DOSE_CONTINGENCY_PCT = D("0.20")
ALARA_REVIEW_THRESHOLD_MREM = D(300)

# --- outage_alara_posture -----------------------------------------------------
ALARA_RESTRICTED_RATIO = D("0.25")
ALARA_RESTRICTED_HOLD_MREM = D(200)

# --- outage_scope_cost_rollup -------------------------------------------------
SCOPE_TIER_1_CEILING = D(5000000)
SCOPE_TIER_2_CEILING = D(20000000)
SCOPE_TIER_1_RATE = D("0.08")
SCOPE_TIER_2_RATE = D("0.12")
SCOPE_TIER_3_RATE = D("0.15")

# --- outage_critical_path -----------------------------------------------------
CONTINGENCY_BY_PRIORITY = {"CRITICAL": D("0.25"), "HIGH": D("0.15"), "DISCRETIONARY": D("0.05")}
UNLINKED_CONTINGENCY_PCT = D("0.10")

# --- outage_schedule_posture --------------------------------------------------
SCHEDULE_AT_RISK_FACTOR = D("1.10")

# --- core_load_reactivity_margin ---------------------------------------------
BASE_SHUTDOWN_MARGIN_PCM = D(800)
FRESH_ASSEMBLY_WORTH_PCM = D(12)
CYCLE_BURNUP_PENALTY_PCM_PER_GWD = D(15)
MIN_SHUTDOWN_MARGIN_PCM = D(1000)

# --- outage_performance_review -----------------------------------------------
WEIGHT_DURATION = D("0.5")
WEIGHT_DOSE = D("0.3")
WEIGHT_COST = D("0.2")

# --- startup_test_reactivity_deviation ---------------------------------------
REACTIVITY_TOLERANCE_PCM = D(100)


def q2(value):
    """Round half up to two decimal places."""
    return D(value).quantize(D("0.01"), rounding=ROUND_HALF_UP)


def dec(value):
    if isinstance(value, Decimal):
        return value
    return D(str(value))


def floor_div_blocks(amount, divisor):
    """Whole completed blocks: the fractional part is discarded entirely."""
    return (dec(amount) / dec(divisor)).to_integral_value(rounding="ROUND_FLOOR")


# =============================================================================
# work_order_priority_score
# =============================================================================
def work_order_priority(wo_type, estimated_hours, estimated_cost_usd,
                        estimated_dose_mrem, regulatory_commitment,
                        safety_function_id, duration_target_hours):
    type_weight = SAFETY_WEIGHT_BY_TYPE[wo_type]
    sf_bonus = SF_BONUS if safety_function_id is not None else D(0)
    reg_bonus = REGULATORY_BONUS if regulatory_commitment else D(0)

    raw_pressure = dec(estimated_hours) / dec(duration_target_hours) * DURATION_PRESSURE_MULTIPLIER
    duration_pressure = min(DURATION_PRESSURE_CAP, q2(raw_pressure))

    dose_penalty = min(DOSE_PENALTY_CAP,
                       floor_div_blocks(estimated_dose_mrem, DOSE_PENALTY_DIVISOR))

    score = q2(type_weight + sf_bonus + reg_bonus + duration_pressure - dose_penalty)

    if score >= PRIORITY_CRITICAL_MIN:
        band = "CRITICAL"
    elif score >= PRIORITY_HIGH_MIN:
        band = "HIGH"
    else:
        band = "DISCRETIONARY"
    return score, band


# =============================================================================
# rwp_committed_dose  (rounding order pinned at each of the four steps)
# =============================================================================
def rwp_doses(dose_rate_mrem_per_hr, planned_duration_hours, shielding_factor,
              worker_count):
    per_worker_raw = (dec(dose_rate_mrem_per_hr)
                      * dec(planned_duration_hours)
                      * (D(1) - dec(shielding_factor)))
    per_worker = q2(per_worker_raw)
    collective = q2(per_worker * D(worker_count))
    contingency = q2(collective * DOSE_CONTINGENCY_PCT)
    committed = q2(collective + contingency)
    alara_required = collective >= ALARA_REVIEW_THRESHOLD_MREM
    return per_worker, collective, contingency, committed, alara_required


# =============================================================================
# core_load_reactivity_margin
# =============================================================================
def reactivity_margin(cycle_length_mwd_mtu, fresh_assembly_count):
    return q2(BASE_SHUTDOWN_MARGIN_PCM
              + FRESH_ASSEMBLY_WORTH_PCM * D(fresh_assembly_count)
              - CYCLE_BURNUP_PENALTY_PCM_PER_GWD * (dec(cycle_length_mwd_mtu) / D(1000)))


# =============================================================================
# outage_scope_cost_rollup  (tier selected from the BASE, flat rate)
# =============================================================================
def scope_cost_rollup(base_sum):
    base = q2(base_sum)
    if base < SCOPE_TIER_1_CEILING:
        rate = SCOPE_TIER_1_RATE
    elif base < SCOPE_TIER_2_CEILING:
        rate = SCOPE_TIER_2_RATE
    else:
        rate = SCOPE_TIER_3_RATE
    contingency = q2(base * rate)
    total = q2(base + contingency)
    return base, contingency, total


# =============================================================================
# outage_schedule_posture
# =============================================================================
def schedule_posture(projected, target):
    projected = dec(projected)
    target = dec(target)
    if projected <= target:
        return "ON_TRACK"
    if projected <= q2(target * SCHEDULE_AT_RISK_FACTOR):
        return "AT_RISK"
    return "RECOVERY_REQUIRED"


# =============================================================================
# outage_alara_posture  (ratio compared UNROUNDED)
# =============================================================================
def alara_posture(remaining, total):
    remaining = dec(remaining)
    total = dec(total)
    if remaining <= 0:
        return "SUSPENDED"
    ratio = remaining / total
    if ratio <= ALARA_RESTRICTED_RATIO:
        return "RESTRICTED"
    return "NORMAL"


# =============================================================================
# startup_test_reactivity_deviation
# =============================================================================
def reactivity_deviation(measured, predicted):
    return q2(abs(dec(measured) - dec(predicted)))


# =============================================================================
# outage_performance_review
# =============================================================================
def variance_pct(actual, baseline):
    return q2((dec(actual) - dec(baseline)) / dec(baseline) * D(100))


def performance_index(duration_pct, dose_pct, cost_pct):
    penalty = (WEIGHT_DURATION * max(D(0), dec(duration_pct))
               + WEIGHT_DOSE * max(D(0), dec(dose_pct))
               + WEIGHT_COST * max(D(0), dec(cost_pct)))
    value = q2(D(100) - penalty)
    if value < 0:
        value = ZERO2
    return value
