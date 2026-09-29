"""Deterministic calculation rules (PRD 3.10).

All arithmetic that must round is carried out on exact rationals
(`fractions.Fraction`) and rounded once, at the end, half-up — never on binary
floats, and never through an intermediate rounding step.
"""
from decimal import Decimal
from fractions import Fraction

import constants


# --- rounding primitives ---------------------------------------------------
def round_half_up(value, places=0):
    """Round an exact rational half-up to `places` decimals; returns Decimal."""
    frac = value if isinstance(value, Fraction) else Fraction(str(value))
    scale = 10 ** places
    scaled = frac * scale
    floor = scaled.numerator // scaled.denominator
    remainder = scaled - floor
    if remainder >= Fraction(1, 2):
        floor += 1
    if places == 0:
        return Decimal(floor)
    return (Decimal(floor) / Decimal(scale)).quantize(Decimal(1).scaleb(-places))


def round_half_up_int(value):
    return int(round_half_up(value, 0))


def ceil_frac(value):
    frac = value if isinstance(value, Fraction) else Fraction(str(value))
    floor = frac.numerator // frac.denominator
    return floor if frac == floor else floor + 1


def floor_frac(value):
    frac = value if isinstance(value, Fraction) else Fraction(str(value))
    return frac.numerator // frac.denominator


# --- risk score composition ------------------------------------------------
def reach_points(deployed_headcount_reach):
    for threshold, points in constants.REACH_BANDS:
        if deployed_headcount_reach >= threshold:
            return points
    return 0


def jurisdiction_points(jurisdictions):
    return constants.JURISDICTION_POINTS_EACH * sum(
        1 for j in (jurisdictions or []) if j in constants.HIGH_SCRUTINY_JURISDICTIONS
    )


def classification_points(use_case):
    return {
        "impact_points": constants.INDIVIDUAL_IMPACT_POINTS[use_case["individual_impact"]],
        "autonomy_points": constants.AUTONOMY_POINTS[use_case["decision_autonomy"]],
        "sensitivity_points": constants.SENSITIVITY_POINTS[use_case["data_sensitivity"]],
        "reach_points": reach_points(use_case["deployed_headcount_reach"]),
        "jurisdiction_points": jurisdiction_points(use_case["jurisdictions"]),
    }


def base_score(points):
    return (
        points["impact_points"]
        + points["autonomy_points"]
        + points["sensitivity_points"]
        + points["reach_points"]
        + points["jurisdiction_points"]
    )


def clamp_risk_score(raw):
    rounded = round_half_up_int(raw)
    if rounded < constants.RISK_SCORE_MIN:
        return constants.RISK_SCORE_MIN
    if rounded > constants.RISK_SCORE_MAX:
        return constants.RISK_SCORE_MAX
    return rounded


def tier_from_score(risk_score):
    for threshold, tier in constants.TIER_BANDS:
        if risk_score >= threshold:
            return tier
    return "MINIMAL"


def is_forced_prohibited(use_case):
    """PRD 2.9/3.2: all four conditions must hold simultaneously — three out of
    four leaves the ordinary bands in charge."""
    return bool(
        use_case["affects_individuals"] is True
        and use_case["individual_impact"] == "CONSEQUENTIAL"
        and use_case["decision_autonomy"] == "FULLY_AUTOMATED"
        and use_case["data_sensitivity"] == "SPECIAL_CATEGORY"
    )


def compute_risk(use_case, vendor_penalty=0, control_credit=0):
    """Return the full point breakdown for either classification variant."""
    points = classification_points(use_case)
    base = base_score(points)
    raw = base + vendor_penalty - control_credit
    score = clamp_risk_score(raw)
    forced = is_forced_prohibited(use_case)
    tier = "PROHIBITED" if forced else tier_from_score(score)
    result = dict(points)
    result.update(
        {
            "base_score": base,
            "vendor_penalty": vendor_penalty,
            "control_credit": control_credit,
            "risk_score": score,
            "risk_tier": tier,
            "forced_prohibited": forced,
        }
    )
    return result


# --- control credit --------------------------------------------------------
def control_credit(cleared_gate_count, passed_eval_count):
    raw = (
        constants.CREDIT_PER_CLEARED_GATE * cleared_gate_count
        + constants.CREDIT_PER_PASSED_EVAL * passed_eval_count
    )
    return min(constants.CONTROL_CREDIT_CAP, raw)


def vendor_penalty_for_asset(asset):
    if asset is None or not asset.get("is_third_party"):
        return 0
    grade = asset.get("vendor_terms_grade")
    return constants.VENDOR_PENALTY_BY_GRADE.get(grade, 0)


# --- vendor terms grading --------------------------------------------------
def retention_points(effective_retention_days):
    for threshold, points in constants.RETENTION_BANDS:
        if effective_retention_days <= threshold:
            return points
    return constants.RETENTION_BAND_OVER


def terms_grade_from_points(points):
    for threshold, grade in constants.TERMS_GRADE_BANDS:
        if points <= threshold:
            return grade
    return constants.TERMS_GRADE_OVER


def grade_vendor_terms(assessment, variant):
    """Return (effective_retention_days, terms_risk_points, terms_grade)."""
    declared = assessment["retention_days"]
    opt_out = bool(assessment["retention_opt_out"])
    provenance = assessment["training_data_provenance"]

    if variant == "CONSERVATIVE_LEGAL":
        if declared is None or not opt_out:
            effective = constants.ASSUMED_WORST_RETENTION_DAYS
        else:
            effective = declared
        provenance_points = constants.PROVENANCE_POINTS[provenance]
        if provenance == "UNDISCLOSED":
            provenance_points += constants.UNDISCLOSED_CONSERVATIVE_SURCHARGE
    else:
        effective = declared
        provenance_points = constants.PROVENANCE_POINTS[provenance]

    points = provenance_points
    points += constants.OUTPUT_RIGHTS_POINTS[assessment["output_rights"]]
    points += retention_points(effective)
    if not opt_out:
        points += constants.NO_OPT_OUT_POINTS
    if not assessment["subprocessors_disclosed"]:
        points += constants.UNDISCLOSED_SUBPROCESSORS_POINTS
    return effective, points, terms_grade_from_points(points)


# --- oversight adequacy ----------------------------------------------------
def adequacy_score(review_mode, sample_pct, escalation_sla_hours, override_capability):
    base = constants.MODE_BASE[review_mode]
    if review_mode == "SAMPLED":
        sample_component = min(
            constants.SAMPLE_COMPONENT_CAP,
            floor_frac(Fraction(sample_pct) * Fraction(3, 10)),
        )
    else:
        sample_component = 0
    sla_component = max(
        0,
        constants.SLA_COMPONENT_BASE
        - floor_frac(Fraction(escalation_sla_hours, constants.SLA_COMPONENT_DIVISOR)),
    )
    override_component = constants.OVERRIDE_BONUS if override_capability else 0
    return min(
        constants.ADEQUACY_CAP,
        base + sample_component + sla_component + override_component,
    )


def required_adequacy(risk_tier, decision_autonomy):
    if risk_tier is None:
        return None
    table = constants.REQUIRED_ADEQUACY.get(risk_tier)
    if table is None:
        return None
    return table[decision_autonomy]


# --- control debt ----------------------------------------------------------
def gate_control_debt(gate_type, open_condition_count, pinned_risk_tier):
    if pinned_risk_tier is None or open_condition_count <= 0:
        return Decimal("0.00")
    weight = Fraction(constants.GATE_WEIGHT[gate_type])
    multiplier = Fraction(constants.TIER_MULTIPLIER[pinned_risk_tier])
    value = weight * Fraction(open_condition_count, constants.CONDITION_DIVISOR) * multiplier
    return round_half_up(value, 2)


def portfolio_control_debt(gates):
    """Plain sum of the already-rounded per-gate values (PRD 3.10)."""
    total = Decimal("0.00")
    for gate in gates:
        total += Decimal(gate["control_debt_index"])
    return total.quantize(Decimal("0.01"))


# --- evaluation profile ----------------------------------------------------
def evaluation_profile(eval_type, risk_tier):
    """Return (required_metric_name, required_metric_threshold, required_sample_size).

    The tier drives the whole profile. An unclassified use case has no tier;
    the least demanding profile is used so the record stays well formed.
    """
    tier = risk_tier if risk_tier in constants.EVAL_THRESHOLDS else "MINIMAL"
    metric = constants.METRIC_BY_EVAL_TYPE[eval_type]
    threshold = float(constants.EVAL_THRESHOLDS[tier][eval_type])
    sample = constants.MIN_SAMPLE_SIZE[tier]
    return metric, threshold, sample


def evaluation_passed(observed_metric_value, threshold, sample_size, required_sample_size):
    """Both comparisons are >=; equality passes. No rounding beforehand."""
    if observed_metric_value is None:
        return False
    if Decimal(str(observed_metric_value)) < Decimal(str(threshold)):
        return False
    if sample_size is None or sample_size < required_sample_size:
        return False
    return True


# --- incident containment --------------------------------------------------
def containment_hours(severity, effective_tier):
    tier = effective_tier if effective_tier in constants.TIER_SPEED_FACTOR else "LIMITED"
    base = constants.CONTAINMENT_BASE_HOURS[severity]
    factor = Fraction(constants.TIER_SPEED_FACTOR[tier])
    return ceil_frac(base * factor)


def monitoring_posture(incidents):
    unresolved = [
        i for i in incidents if i["status"] in constants.UNRESOLVED_INCIDENT_STATUSES
    ]
    if any(i["severity"] == "SEV1" for i in unresolved):
        return "IMPAIRED"
    if len(unresolved) >= 1:
        return "WATCH"
    return "HEALTHY"


# --- shadow grace ---------------------------------------------------------
def grace_days_total(environment, grace_days_granted):
    return constants.BASE_GRACE_DAYS[environment] + (grace_days_granted or 0)


# --- reassessment cadence -------------------------------------------------
def reassessment_interval_days(final_risk_tier):
    return constants.REASSESSMENT_INTERVAL_DAYS.get(final_risk_tier, 180)
