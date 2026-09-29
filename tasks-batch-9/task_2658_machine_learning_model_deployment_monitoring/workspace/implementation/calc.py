"""The eleven pinned calculations of the PRD (sections 2.5, 3.3-3.9)."""

from decimal import Decimal

import db
from db import dec, q2, q4, trunc2

ONE = Decimal(1)
ZERO = Decimal(0)
EPS = Decimal("0.0001")

# ---- ramp planner constants (PRD 3.4) -----------------------------------
RAMP_CHECKPOINTS = {
    "REALTIME": [Decimal("5"), Decimal("15"), Decimal("35"), Decimal("65"),
                 Decimal("100")],
    "SHADOW": [Decimal("10"), Decimal("50"), Decimal("100")],
    "BATCH": [Decimal("50"), Decimal("100")],
}
MAX_STEP_PCT = Decimal("30")
REALTIME_HEADROOM_RESERVE_PCT = Decimal("5")

# ---- health score weights (PRD 3.5) ------------------------------------
W_ACCURACY = Decimal("0.45")
W_DISTRIBUTION = Decimal("0.30")
W_LATENCY = Decimal("0.25")
DISTRIBUTION_TOLERANCE = Decimal("0.20")
UNLABELLED_IMPUTATION_RATE = Decimal("0.60")
HEALTH_RECOVERY_MIN = Decimal("80.00")

# ---- drift (PRD 3.6) ---------------------------------------------------
DRIFT_CRITICAL = Decimal("0.25")
DRIFT_WARN = Decimal("0.10")

# ---- skew (PRD 3.6) ----------------------------------------------------
SKEW_FAIL = Decimal("1.25")
SKEW_WARN = Decimal("1.10")

# ---- urgency (PRD 3.6) -------------------------------------------------
DRIFT_WEIGHT = Decimal("120")
SKEW_WEIGHT = Decimal("80")
STALENESS_PER_DAY = Decimal("0.5")
ESCALATION_TIERS = [(Decimal("0"), Decimal("0")), (Decimal("20"), Decimal("10")),
                    (Decimal("45"), Decimal("25")), (Decimal("70"), Decimal("40"))]
URGENCY_CEILING = Decimal("100")
RETRAIN_REQUIRED_MIN = Decimal("45")
TRIGGER_STALE_DAYS = 90

# ---- promotion score (PRD 3.7) -----------------------------------------
METRIC_ORDER = ["ACCURACY_PROXY", "CALIBRATION", "LATENCY", "COST"]
METRIC_WEIGHTS = {
    "ACCURACY_PROXY": Decimal("0.50"),
    "CALIBRATION": Decimal("0.20"),
    "LATENCY": Decimal("0.15"),
    "COST": Decimal("0.15"),
}
LOWER_IS_BETTER = ("LATENCY", "COST")
PROMOTION_SCORE_MIN = Decimal("0.0300")
MIN_LABELED_PREDICTIONS = 1000
LATENCY_REGRESSION_MS = Decimal("25")
MAX_EVALUATION_EXTENSIONS = 2
EXTENSION_DAYS = 7
EXTENSION_SAMPLES = 500

# ---- documentation (PRD 3.3) -------------------------------------------
DOC_SECTION_KEYS = ["INTENDED_USE", "TRAINING_DATA", "EVALUATION", "LIMITATIONS",
                    "ETHICAL_REVIEW"]
REPRO_ARTIFACT_KEYS = ["TRAINING_CODE_COMMIT", "ENV_LOCKFILE_DIGEST", "RANDOM_SEED",
                       "FEATURE_SPEC_HASH"]
DOC_COMPLETENESS_MIN = Decimal("80.00")
REPRODUCIBILITY_MIN = Decimal("100.00")

SERVING_STATES = ("RAMPING", "HELD", "LIVE")
LEDGER_STATES = ("RAMPING", "HELD", "LIVE", "DRAINING")
RAMP_BLOCKING_INCIDENTS = ("OPEN", "MITIGATING", "ESCALATED")
CRITICAL_CLEAR_BLOCKING_INCIDENTS = ("OPEN", "MITIGATING", "MONITORING", "ESCALATED")
FAILED_SKEW_STATES = ("FAIL_SKEW", "FAIL_MISSING_FEATURE")


# =========================================================================
# 1. documentation_and_reproducibility_score
# =========================================================================
def doc_scores(doc_sections, repro_artifacts):
    docs = set(doc_sections or [])
    repro = set(repro_artifacts or [])
    doc_present = sum(1 for k in DOC_SECTION_KEYS if k in docs)
    repro_present = sum(1 for k in REPRO_ARTIFACT_KEYS if k in repro)
    doc_pct = q2(Decimal(100) * Decimal(doc_present) / Decimal(5))
    repro_pct = q2(Decimal(100) * Decimal(repro_present) / Decimal(4))
    return doc_pct, repro_pct


def doc_gate_ok(version):
    return (version["doc_completeness_pct"] >= DOC_COMPLETENESS_MIN
            and version["reproducibility_score"] >= REPRODUCIBILITY_MIN)


# =========================================================================
# 2. composite_health_score
# =========================================================================
def health_score(window, version, variant):
    positive_rate = dec(window["positive_rate"])
    baseline_positive_rate = dec(version["baseline_positive_rate"])
    distribution = ONE - (abs(positive_rate - baseline_positive_rate)
                          / DISTRIBUTION_TOLERANCE)
    if distribution < 0:
        distribution = ZERO

    baseline_latency = dec(version["baseline_p95_latency_ms"])
    observed_latency = dec(window["p95_latency_ms"])
    if observed_latency == 0:
        latency = ZERO
    else:
        latency = baseline_latency / observed_latency
    if latency > ONE:
        latency = ONE
    if latency < ZERO:
        latency = ZERO

    labeled = Decimal(window["labeled_prediction_count"])
    correct = Decimal(window["correct_labeled_count"])
    predictions = Decimal(window["prediction_count"])
    if variant == "FINAL":
        if predictions == 0:
            accuracy = ZERO
        else:
            accuracy = (correct + UNLABELLED_IMPUTATION_RATE
                        * (predictions - labeled)) / predictions
    else:
        accuracy = ZERO if labeled == 0 else correct / labeled

    raw = Decimal(100) * (W_ACCURACY * accuracy + W_DISTRIBUTION * distribution
                          + W_LATENCY * latency)
    score = q2(raw)
    baseline_delta = q2(score - Decimal(100) * dec(version["baseline_accuracy"]))
    return score, baseline_delta


# =========================================================================
# 3. drift_index (population stability index over five bins)
# =========================================================================
def drift_index(observed, expected):
    total = ZERO
    for obs_raw, exp_raw in zip(observed, expected):
        obs = dec(obs_raw)
        exp = dec(exp_raw)
        obs_safe = obs if obs > EPS else EPS
        exp_safe = exp if exp > EPS else EPS
        total += (obs - exp) * (obs_safe / exp_safe).ln()
    return q4(total)


def drift_severity(index):
    if index >= DRIFT_CRITICAL:
        return "CRITICAL"
    if index >= DRIFT_WARN:
        return "WARN"
    return "NONE"


# =========================================================================
# 4. feature_skew_ratio
# =========================================================================
def skew_evaluation(training_stats, serving_stats):
    training_names = sorted(training_stats.keys())
    missing = sorted([n for n in training_names if n not in serving_stats])

    max_ratio = None
    max_feature = None
    for name in training_names:
        if name in missing:
            continue
        a = abs(dec(training_stats[name]["mean"]))
        b = abs(dec(serving_stats[name]["mean"]))
        a = a if a > EPS else EPS
        b = b if b > EPS else EPS
        hi, lo = (a, b) if a >= b else (b, a)
        ratio = q4(hi / lo)
        if max_ratio is None or ratio > max_ratio:
            max_ratio = ratio
            max_feature = name

    if max_ratio is None:
        max_ratio = Decimal("1.0000")
        max_feature = None

    if missing:
        status = "FAIL_MISSING_FEATURE"
    elif max_ratio >= SKEW_FAIL:
        status = "FAIL_SKEW"
    elif max_ratio >= SKEW_WARN:
        status = "WARN"
    else:
        status = "PASS"
    return max_ratio, max_feature, missing, status


# =========================================================================
# 5. retraining_urgency
# =========================================================================
def retraining_urgency(drift_report, skew_check, evidence_version, clock_now):
    drift_contribution = ZERO
    if drift_report is not None:
        drift_contribution = DRIFT_WEIGHT * dec(drift_report["drift_index"])

    skew_contribution = ZERO
    if skew_check is not None:
        raw = SKEW_WEIGHT * (dec(skew_check["max_skew_ratio"]) - ONE)
        skew_contribution = raw if raw > 0 else ZERO

    staleness = ZERO
    if evidence_version is not None and evidence_version.get("approved_at"):
        days = db.whole_days_between(evidence_version["approved_at"], clock_now)
        if days > 0:
            staleness = STALENESS_PER_DAY * Decimal(days)

    base = q2(drift_contribution + skew_contribution + staleness)

    bonus = ZERO
    for floor, tier_bonus in ESCALATION_TIERS:
        if base >= floor:
            bonus = tier_bonus
    total = q2(base * (ONE + bonus / Decimal(100)))
    if total > URGENCY_CEILING:
        total = q2(URGENCY_CEILING)

    if total >= Decimal("75"):
        band = "CRITICAL"
    elif total >= Decimal("50"):
        band = "HIGH"
    elif total >= Decimal("25"):
        band = "MEDIUM"
    else:
        band = "LOW"

    return {
        "base_urgency": base,
        "escalation_tier_bonus_pct": q2(bonus),
        "total_urgency": total,
        "priority_band": band,
        "retrain_required": total >= RETRAIN_REQUIRED_MIN,
        "stale_after": db.add_days(clock_now, TRIGGER_STALE_DAYS),
    }


# =========================================================================
# 6. challenger_promotion_score
# =========================================================================
def promotion_score(champion_metrics, challenger_metrics):
    lines = {}
    for metric in METRIC_ORDER:
        champion = dec(champion_metrics[metric])
        challenger = dec(challenger_metrics[metric])
        denominator = abs(champion)
        if denominator < EPS:
            denominator = EPS
        normalised = (challenger - champion) / denominator
        if metric in LOWER_IS_BETTER:
            normalised = -normalised
        lines[metric] = q4(METRIC_WEIGHTS[metric] * normalised)
    total = ZERO
    for metric in METRIC_ORDER:
        total += lines[metric]
    return lines, q4(total)


# =========================================================================
# 7. traffic_ramp_step_plan
# =========================================================================
def ramp_plan(deployment, endpoint):
    """Returns (nominal_target, granted_delta, new_traffic, advance) or raises."""
    from errors import ApiError

    checkpoints = RAMP_CHECKPOINTS[deployment["pattern"]]
    index = deployment["ramp_step_index"]
    if index >= len(checkpoints):
        raise ApiError("ERR_RAMP_ALREADY_COMPLETE")

    nominal_target = checkpoints[index]
    current = dec(deployment["traffic_pct"])
    raw_step = nominal_target - current

    if deployment["health_state"] == "DEGRADED":
        capped = trunc2(raw_step * Decimal("0.5"))
    else:
        capped = raw_step

    step = capped if capped < MAX_STEP_PCT else MAX_STEP_PCT

    if (deployment["pattern"] == "REALTIME"
            and nominal_target < checkpoints[-1]):
        reserve = REALTIME_HEADROOM_RESERVE_PCT
    else:
        reserve = ZERO

    headroom = (dec(endpoint["max_traffic_pct"]) - reserve
                - dec(endpoint["allocated_traffic_pct"]))
    granted = step if step < headroom else headroom
    if granted < 0:
        granted = ZERO
    if granted == 0:
        raise ApiError("ERR_ENDPOINT_CAPACITY_EXHAUSTED")

    new_traffic = q2(current + granted)
    advance = new_traffic == nominal_target
    return nominal_target, q2(granted), new_traffic, advance
