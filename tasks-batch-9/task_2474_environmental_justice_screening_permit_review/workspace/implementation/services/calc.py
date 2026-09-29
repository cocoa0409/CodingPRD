"""Pure calculation rules (SCAFFOLD Table 3 / PRD section 3).

Every rounding point below is exactly where the PRD names one, and every tier or
cap selection is keyed on the input term the PRD names, never on the output.
"""
from decimal import Decimal, ROUND_HALF_UP

import constants as C

D = Decimal
ZERO = D("0.00")


def rnd(value, places=2):
    exponent = D(1).scaleb(-places)
    return D(value).quantize(exponent, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- ej_screen_score
def component_mean(rows, percentile_key, category):
    selected = [r for r in rows if r["category"] == category]
    if not selected:
        return ZERO
    total = sum((r[percentile_key] for r in selected), D(0))
    return rnd(total / D(len(selected)), 2)


def ej_screen_score(rows, percentile_key, enforcement_points):
    """Returns (score, pollution_component, health_component, demographic_component)."""
    pollution = component_mean(rows, percentile_key, "POLLUTION")
    health = component_mean(rows, percentile_key, "HEALTH")
    demographic = component_mean(rows, percentile_key, "DEMOGRAPHIC")
    combined = (
        (C.POLLUTION_WEIGHT * pollution) + (C.HEALTH_WEIGHT * health)
    ) * (demographic / D(100))
    score_pre = rnd(combined, 2)
    penalised = score_pre + C.ENFORCEMENT_POINT_WEIGHT * D(enforcement_points)
    score = rnd(min(D("100.00"), penalised), 2)
    return score, pollution, health, demographic


def designation_for(score):
    if score >= C.SEVERE_THRESHOLD:
        return "SEVERELY_OVERBURDENED"
    if score >= C.DESIGNATION_THRESHOLD:
        return "OVERBURDENED"
    return "UNDESIGNATED"


def translation_required_for(limited_english_pct):
    return limited_english_pct >= C.TRANSLATION_TRIGGER_PCT


# ------------------------------------------------------- applicability_determination
def applicability_trigger_codes(facility, area, application):
    codes = []
    if facility["facility_type"] in C.ENHANCED_FACILITY_TYPES:
        codes.append("FACILITY_TYPE")
    if facility["distance_to_area_centroid_m"] <= C.PROXIMITY_TRIGGER_M:
        codes.append("PROXIMITY")
    if area["designation"] in ("OVERBURDENED", "SEVERELY_OVERBURDENED"):
        codes.append("DESIGNATION")
    if application["proposed_emissions_tpy"] >= C.EMISSIONS_TRIGGER_TPY:
        codes.append("EMISSIONS_THRESHOLD")
    if facility["compliance_status"] == "VIOLATION_ON_RECORD":
        codes.append("PRIOR_VIOLATION")
    return codes


# ---------------------------------------------------------- cumulative_impact_index
def refined_decay(receptor_distance_m):
    if receptor_distance_m <= C.REFINED_DECAY_NEAR_M:
        return D("1.00")
    if receptor_distance_m <= C.REFINED_DECAY_MID_M:
        return D("0.75")
    return D("0.50")


def cumulative_impact_index(baseline_burden_score, proposed_emissions_tpy,
                            baseline_load_tpy, method, dispersion_factor,
                            receptor_distance_m):
    """Pinned order: increment -> exposure -> weighted increment -> pre -> clamp."""
    proposed_increment_pct = rnd(
        (proposed_emissions_tpy / baseline_load_tpy) * D(100), 2
    )
    if method == "SCREENING_LEVEL":
        exposure_factor = D("1.0000")
    else:
        decay = refined_decay(receptor_distance_m)
        exposure_factor = rnd(dispersion_factor * decay, 4)
    weighted_increment = rnd(
        proposed_increment_pct * exposure_factor * C.INCREMENT_WEIGHT, 2
    )
    index_pre = rnd(baseline_burden_score * C.BASELINE_WEIGHT + weighted_increment, 2)
    index = rnd(min(D("100.00"), index_pre), 2)
    return proposed_increment_pct, exposure_factor, index


def disproportionate(index):
    return index >= C.DISPROPORTIONATE_THRESHOLD


def data_confidence_for(active_indicator_count, data_status):
    if active_indicator_count == 0 or data_status == "STALE":
        return "LOW"
    return "HIGH"


# ------------------------------------------------------ mitigation_credit_aggregation
def condition_credit(condition):
    efficacy = C.EFFICACY[condition["condition_type"]]
    enforce_factor = D("1.00") if condition["enforceable"] else C.NON_ENFORCEABLE_FACTOR
    return rnd(condition["reduction_tpy"] * efficacy * enforce_factor, 2)


def total_mitigation_credit(active_conditions):
    """Round per condition first, then sum the rounded values (pinned order)."""
    running = D(0)
    for condition in active_conditions:
        running += condition["credit_tpy"]
    return rnd(running, 2)


def approved_net_emissions(proposed_emissions_tpy, total_credit):
    return rnd(max(ZERO, proposed_emissions_tpy - total_credit), 2)


# ------------------------------------------------------------ residual_impact_index
def residual_impact_index(pre, total_credit, proposed_emissions_tpy):
    if proposed_emissions_tpy == 0:
        credit_ratio = D("1.0000")
    else:
        credit_ratio = min(D("1.0000"), rnd(total_credit / proposed_emissions_tpy, 4))
    if pre >= C.CAP_TIER_HIGH_INDEX:
        mitigation_cap = D("0.60")
    elif pre >= C.CAP_TIER_MID_INDEX:
        mitigation_cap = D("0.75")
    else:
        mitigation_cap = D("1.00")
    effective_reduction = min(credit_ratio, mitigation_cap)
    return rnd(pre * (D(1) - effective_reduction), 2)


# ------------------------------------------------------- community_benefit_obligation
def community_benefit(base, designation):
    if base >= C.BENEFIT_TIER_HIGH_USD:
        surcharge_rate = D("0.12")
    elif base >= C.BENEFIT_TIER_MID_USD:
        surcharge_rate = D("0.08")
    else:
        surcharge_rate = D("0.05")
    if designation == "SEVERELY_OVERBURDENED":
        multiplier = D("1.25")
    elif designation == "OVERBURDENED":
        multiplier = D("1.10")
    else:
        multiplier = D("1.00")
    surcharge = rnd(base * surcharge_rate * multiplier, 2)
    total = rnd(base + surcharge, 2)
    return surcharge, total


def minimum_benefit_required(approved_net):
    return rnd(C.MIN_BENEFIT_PER_TPY * approved_net, 2)


def area_load_cap(baseline_load_tpy):
    return rnd(C.AREA_LOAD_CAP_MULTIPLIER * baseline_load_tpy, 2)


# ------------------------------------------------------------ required_comment_days
def required_comment_days(designation, translation_required, governing_index):
    days = C.BASE_COMMENT_DAYS
    if designation == "OVERBURDENED":
        days += 15
    if designation == "SEVERELY_OVERBURDENED":
        days += 30
    if translation_required:
        days += 15
    if governing_index is not None and governing_index >= C.DISPROPORTIONATE_THRESHOLD:
        days += 10
    return min(days, C.MAX_COMMENT_DAYS)


def reopen_added_days(required_days, granted_days):
    headroom = C.MAX_COMMENT_DAYS - (required_days + granted_days)
    return min(C.REOPEN_EXTENSION_DAYS, max(0, headroom))


# --------------------------------------------------------- inspection_priority_score
def inspection_priority_score(county_score, severity, repeat_count,
                              facility_violation, severely_overburdened):
    score = (
        C.AREA_WEIGHT * county_score
        + C.SEVERITY_POINTS[severity]
        + min(C.REPEAT_CAP_POINTS, C.REPEAT_POINTS_PER_PRIOR * D(repeat_count))
        + (D(10) if facility_violation else D(0))
        + (D(5) if severely_overburdened else D(0))
    )
    return rnd(score, 2)


def priority_tier_for(score):
    if score >= C.TIER_1_MIN:
        return "TIER_1"
    if score >= C.TIER_2_MIN:
        return "TIER_2"
    return "TIER_3"
