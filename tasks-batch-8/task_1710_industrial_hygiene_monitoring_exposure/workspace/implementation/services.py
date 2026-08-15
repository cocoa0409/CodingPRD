"""Business logic: counters, state cascades, calculations, sweeps.

Implements PRD section 3 and SCAFFOLD calculation rules exactly, using Decimal
arithmetic with round-half-up at every pinned step.
"""

import math
from datetime import timedelta
from decimal import Decimal

import db
from helpers import r1, r2, r3, r4, now_ts, today, touch, stamp_new

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD calculations table)
# ---------------------------------------------------------------------------

FULL_SHIFT_MIN = 420
SHIFT_BASIS_MIN = 480
DRIFT_LIMIT_PCT = Decimal("5.00")

T95 = {1: 6.314, 2: 2.920, 3: 2.353, 4: 2.132, 5: 2.015,
       6: 1.943, 7: 1.895, 8: 1.860, 9: 1.833, 10: 1.812}

RESAMPLE_INTERVAL_DAYS = {
    "ABOVE_PEL": 30,
    "UNCERTAIN": 90,
    "BELOW_PEL_MONITOR": 180,
    "BELOW_ACTION": 360,
}
VERIFICATION_DUE_DAYS = 14
NOTIFICATION_WORKING_DAYS = 15

MIN_SAMPLES = 3
FOLLOWUP_ADJUSTMENT = 3
VERIFICATION_FLAT = 3


# ---------------------------------------------------------------------------
# required_sample_count (tiered lookup; SCAFFOLD calc required_sample_count)
# ---------------------------------------------------------------------------

def required_sample_count(headcount, current_class, purpose):
    if purpose == "VERIFICATION":
        return VERIFICATION_FLAT
    h = headcount
    if h <= 7:
        base = h
    elif h <= 9:
        base = 7
    elif h == 10:
        base = 8
    elif h <= 12:
        base = 9
    elif h <= 14:
        base = 10
    elif h <= 17:
        base = 11
    elif h <= 20:
        base = 12
    elif h <= 24:
        base = 13
    elif h <= 29:
        base = 14
    elif h <= 37:
        base = 15
    elif h <= 49:
        base = 16
    else:
        base = 17
    adj = FOLLOWUP_ADJUSTMENT if current_class in ("UNCERTAIN", "ABOVE_PEL") else 0
    return max(MIN_SAMPLES, base + adj)


# ---------------------------------------------------------------------------
# Plan counters / regression (PRD sections 2.10, 3.3)
# ---------------------------------------------------------------------------

def recompute_plan_counts(plan):
    """Recompute active_sample_count / analyzed_valid_count.

    Per PRD section 2.10 the recomputation by itself does NOT advance the
    plan's version; only an actual plan status transition does.
    """
    active = 0
    analyzed = 0
    for s in db.field_samples.values():
        if s["sampling_plan_id"] != plan["id"] or s["sample_type"] != "PERSONAL":
            continue
        if s["status"] in ("COLLECTED", "SEALED", "ANALYZED"):
            active += 1
        if s["status"] == "ANALYZED":
            analyzed += 1
    plan["active_sample_count"] = active
    plan["analyzed_valid_count"] = analyzed


def regress_plan_if_needed(plan):
    """Regression loops of PRD section 3.3 after a sample invalidation."""
    if plan["status"] == "FIELD_COMPLETE" and plan["active_sample_count"] < plan["required_sample_count"]:
        plan["status"] = "APPROVED"
        touch(plan)
    elif plan["status"] == "LAB_COMPLETE" and plan["analyzed_valid_count"] < plan["required_sample_count"]:
        plan["status"] = "APPROVED"
        touch(plan)
        # Cascade hop 4: void this plan's unsigned assessments (SIGNED is immutable).
        for a in db.assessments.values():
            if a["sampling_plan_id"] == plan["id"] and a["review_status"] in ("DRAFT", "UNDER_REVIEW"):
                a["review_status"] = "VOID"
                touch(a)


def maybe_complete_lab(plan):
    """FIELD_COMPLETE -> LAB_COMPLETE once every active PERSONAL sample is
    ANALYZED and analyzed_valid_count >= required_sample_count."""
    if plan["status"] != "FIELD_COMPLETE":
        return
    if plan["analyzed_valid_count"] < plan["required_sample_count"]:
        return
    for s in db.field_samples.values():
        if (s["sampling_plan_id"] == plan["id"] and s["sample_type"] == "PERSONAL"
                and s["status"] in ("COLLECTED", "SEALED")):
            return
    plan["status"] = "LAB_COMPLETE"
    touch(plan)


def invalidate_sample(sample, reason):
    """Shared invalidation side effects (PRD section 3.4): set reason, bump
    sample version, release the pump-calibration link, recompute the plan's
    counters, and regress the plan when the completion criteria break."""
    sample["status"] = "INVALIDATED"
    sample["invalidate_reason"] = reason
    touch(sample)
    cal_id = sample.get("pre_calibration_id")
    if cal_id:
        cal = db.pump_calibrations.get(cal_id)
        if cal is not None and cal.get("linked_sample_id") == sample["id"]:
            cal["linked_sample_id"] = None
            touch(cal)
    plan = db.sampling_plans.get(sample["sampling_plan_id"])
    if plan is not None:
        recompute_plan_counts(plan)
        regress_plan_if_needed(plan)


# ---------------------------------------------------------------------------
# Pump drift (SCAFFOLD calc pump_drift)
# ---------------------------------------------------------------------------

def compute_drift(pre_flow, post_flow):
    """drift_pct = r2(|post - pre| / pre * 100); INVALID iff strictly > 5.00."""
    drift = r2(abs(post_flow - pre_flow) / pre_flow * Decimal("100"))
    result = "INVALID" if drift > DRIFT_LIMIT_PCT else "VALID"
    return drift, result


# ---------------------------------------------------------------------------
# Air volume / concentration / TWA chain (SCAFFOLD air_volume_concentration
# and sample_twa; pinned step order, rounding at every step)
# ---------------------------------------------------------------------------

def analyze_sample(sample, mass_ug, is_detect):
    """Fill the sample's computed fields on SEALED -> ANALYZED.

    PERSONAL samples run the full pinned chain; FIELD_BLANK samples carry no
    pump/calibration, so only is_detect is populated (their volume,
    concentration, and TWA stay null and never enter any statistic).
    """
    if sample["sample_type"] == "PERSONAL":
        plan = db.sampling_plans[sample["sampling_plan_id"]]
        cal = db.pump_calibrations[sample["pre_calibration_id"]]
        if plan["volume_basis"] == "MEAN_FLOW":
            flow_used = r3((cal["pre_flow_lpm"] + cal["post_flow_lpm"]) / Decimal("2"))
        else:  # PRE_FLOW: pre_flow_lpm exactly as entered, no averaging/rounding
            flow_used = cal["pre_flow_lpm"]
        volume = r1(flow_used * Decimal(sample["duration_minutes"]))
        concentration = r4(mass_ug / volume)
        duration = sample["duration_minutes"]
        if duration >= FULL_SHIFT_MIN or plan["unsampled_time_rule"] == "ZERO_FILL":
            twa = r4(concentration * Decimal(duration) / Decimal(SHIFT_BASIS_MIN))
        else:  # short sample + WORST_CASE: whole shift at measured concentration
            twa = concentration
        sample["air_volume_liters"] = volume
        sample["concentration_mg_m3"] = concentration
        sample["sample_twa_mg_m3"] = twa
    sample["is_detect"] = is_detect
    sample["status"] = "ANALYZED"
    touch(sample)


def find_result_for_sample(sample_id):
    for res in db.lab_results.values():
        if res["field_sample_id"] == sample_id:
            return res
    return None


# ---------------------------------------------------------------------------
# Blank-contamination cascade (PRD section 3.5)
# ---------------------------------------------------------------------------

def run_contamination_cascade(batch, triggering_sample):
    """A FIELD_BLANK result at/above LOD contaminates the batch and invalidates
    every sibling sample already ANALYZED in the batch."""
    batch["contaminated"] = True
    siblings = []
    for res in db.lab_results.values():
        if res["lab_batch_id"] != batch["id"] or res["field_sample_id"] == triggering_sample["id"]:
            continue
        sib = db.field_samples.get(res["field_sample_id"])
        if sib is not None and sib["status"] == "ANALYZED":
            siblings.append(sib)
    siblings.sort(key=lambda e: (e["created_at"], e["_seq"]))
    for sib in siblings:
        invalidate_sample(sib, "BLANK_CONTAMINATION")


# ---------------------------------------------------------------------------
# Assessment statistics (SCAFFOLD censored_substitution + assessment_statistics)
# ---------------------------------------------------------------------------

def _classification_thresholds(seg):
    limit = db.exposure_limits[seg["exposure_limit_id"]]
    limit_l = limit["limit_mg_m3"]
    action_a = limit_l * limit["action_fraction"]
    return limit, limit_l, action_a


def classify(ucl, lcl, limit_l, action_a):
    """Strict '>' throughout, rules evaluated in pinned order (PRD 3.6).

    ucl / lcl / limit_l / action_a are Decimals."""
    if lcl > limit_l:
        return "ABOVE_PEL"
    if ucl > limit_l:
        return "UNCERTAIN"
    if ucl > action_a:
        return "BELOW_PEL_MONITOR"
    return "BELOW_ACTION"


def compute_assessment_stats(assessment, plan, seg):
    """Populate n_valid, substitution_rule, stats, exposure_class, and stash
    unrounded confidence limits for the later APF adjustment."""
    samples = [s for s in db.field_samples.values()
               if s["sampling_plan_id"] == plan["id"]
               and s["sample_type"] == "PERSONAL"
               and s["status"] == "ANALYZED"]
    samples.sort(key=lambda e: (e["created_at"], e["_seq"]))
    n = len(samples)
    assessment["n_valid"] = n

    detects = sum(1 for s in samples if s["is_detect"])
    if n >= 3 and 2 * detects >= n:
        rule = "SQRT2"
    else:
        rule = "HALF"
    assessment["substitution_rule"] = rule

    # Censored substitution: non-detects enter at their LOD-equivalent TWA.
    sqrt2 = Decimal(2).sqrt()
    xs = []
    for s in samples:
        if s["is_detect"]:
            xs.append(s["sample_twa_mg_m3"])
        else:
            res = find_result_for_sample(s["id"])
            batch = db.lab_batches[res["lab_batch_id"]]
            lod_twa = r4(r4(batch["lod_ug"] / s["air_volume_liters"])
                         * Decimal(s["duration_minutes"]) / Decimal(SHIFT_BASIS_MIN))
            if rule == "SQRT2":
                xs.append(r4(lod_twa / sqrt2))
            else:
                xs.append(r4(lod_twa / Decimal("2")))

    limit, limit_l, action_a = _classification_thresholds(seg)

    if limit["limit_type"] == "CEILING":
        # No statistics; classify on the maximum measured concentration.
        assessment["geo_mean"] = None
        assessment["gsd"] = None
        assessment["ucl95"] = None
        assessment["lcl95"] = None
        assessment["_ucl_unrounded"] = None
        assessment["_lcl_unrounded"] = None
        cmax = max((s["concentration_mg_m3"] for s in samples), default=Decimal("0"))
        if cmax > limit_l:
            klass = "ABOVE_PEL"
        elif cmax > action_a:
            klass = "BELOW_PEL_MONITOR"
        else:
            klass = "BELOW_ACTION"
        assessment["exposure_class"] = klass
        return

    if n == 0:
        # Unreachable through the API (LAB_COMPLETE implies >= 3 analyzed), but
        # never crash: degenerate empty set yields no statistics.
        assessment["geo_mean"] = None
        assessment["gsd"] = None
        assessment["ucl95"] = None
        assessment["lcl95"] = None
        assessment["_ucl_unrounded"] = None
        assessment["_lcl_unrounded"] = None
        assessment["exposure_class"] = "BELOW_ACTION"
        return

    ys = [math.log(float(x)) for x in xs]
    ybar = sum(ys) / n
    if n > 1:
        s = math.sqrt(sum((y - ybar) ** 2 for y in ys) / (n - 1))
    else:
        s = 0.0  # pinned: single-value set has zero dispersion

    if s == 0.0:
        # All values identical (or n == 1): UCL = LCL = GM exactly.
        gm_f = float(xs[0])
        gsd_f = 1.0
        ucl_f = gm_f
        lcl_f = gm_f
    else:
        df = min(n - 1, 10)
        t = T95[df]
        half = t * s / math.sqrt(n)
        gm_f = math.exp(ybar)
        gsd_f = math.exp(s)
        ucl_f = math.exp(ybar + half)
        lcl_f = math.exp(ybar - half)

    assessment["geo_mean"] = r4(Decimal(str(gm_f)))
    assessment["gsd"] = r4(Decimal(str(gsd_f)))
    assessment["ucl95"] = r4(Decimal(str(ucl_f)))
    assessment["lcl95"] = r4(Decimal(str(lcl_f)))
    assessment["_ucl_unrounded"] = ucl_f
    assessment["_lcl_unrounded"] = lcl_f

    # Classification uses the UNROUNDED confidence limits (PRD section 2.6).
    assessment["exposure_class"] = classify(
        Decimal(str(ucl_f)), Decimal(str(lcl_f)), limit_l, action_a)


def compute_adjusted_class(assessment, seg):
    """APF adjustment evaluated at sign time, after the raw class is fixed
    (SCAFFOLD calc apf_adjusted_class). Informational only."""
    limit, limit_l, action_a = _classification_thresholds(seg)
    if limit["limit_type"] == "CEILING":
        return None
    ucl_f = assessment.get("_ucl_unrounded")
    lcl_f = assessment.get("_lcl_unrounded")
    if ucl_f is None or lcl_f is None:
        return None
    qualifying = [c for c in db.controls.values()
                  if c["exposure_assessment_id"] == assessment["id"]
                  and c["control_type"] == "PPE_RESPIRATOR"
                  and c["status"] in ("ACCEPTED", "IMPLEMENTED", "VERIFIED")]
    if not qualifying:
        return None
    control = max(qualifying, key=lambda c: (c["created_at"], c["_seq"]))
    apf = control["assigned_protection_factor"]
    ucl_adj = r4(Decimal(str(ucl_f)) / apf)
    lcl_adj = r4(Decimal(str(lcl_f)) / apf)
    return classify(ucl_adj, lcl_adj, limit_l, action_a)


# ---------------------------------------------------------------------------
# Date arithmetic (SCAFFOLD calcs reassessment_due_date / notification_due_date
# / retention_until)
# ---------------------------------------------------------------------------

def add_days(d, n):
    return d + timedelta(days=n)


def add_years(d, years):
    """Same month/day N calendar years later (Feb 29 clamps to Feb 28)."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def working_days_after(start_date, n=NOTIFICATION_WORKING_DAYS):
    """The date D such that exactly n Mon-Fri days fall in (start_date, D]."""
    d = start_date
    count = 0
    while count < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return d


# ---------------------------------------------------------------------------
# Clock sweeps (PRD section 2.5): strictly-greater date comparisons
# ---------------------------------------------------------------------------

def run_clock_sweeps():
    now_date = today()
    # 1. Clearances CLEARED -> EXPIRED, cascading to their PASSED fit tests.
    for c in db.medical_clearances.values():
        if c["status"] == "CLEARED" and c["expiry_date"] is not None:
            if now_date > _iso_to_date(c["expiry_date"]):
                c["status"] = "EXPIRED"
                touch(c)
                for ft in db.fit_tests.values():
                    if ft["medical_clearance_id"] == c["id"] and ft["status"] == "PASSED":
                        ft["status"] = "EXPIRED"
                        touch(ft)
    # 2. Fit tests PASSED -> EXPIRED on their own expiry date.
    for ft in db.fit_tests.values():
        if ft["status"] == "PASSED" and ft["expiry_date"] is not None:
            if now_date > _iso_to_date(ft["expiry_date"]):
                ft["status"] = "EXPIRED"
                touch(ft)
    # 3. Notifications PENDING -> OVERDUE past their due date.
    for n in db.notifications.values():
        if n["status"] == "PENDING" and n["due_date"] is not None:
            if now_date > _iso_to_date(n["due_date"]):
                n["status"] = "OVERDUE"
                touch(n)


def _iso_to_date(s):
    from datetime import date as _date
    return _date.fromisoformat(s)


# ---------------------------------------------------------------------------
# Verification plan spawn (control implement; PRD section 3.7)
# ---------------------------------------------------------------------------

def spawn_verification_plan(seg_id, user_id):
    now_date = today()
    plan = {
        "seg_id": seg_id,
        "purpose": "VERIFICATION",
        "planned_start_date": add_days(now_date, 1).isoformat(),
        "planned_end_date": add_days(now_date, 30).isoformat(),
        "unsampled_time_rule": "ZERO_FILL",
        "volume_basis": "MEAN_FLOW",
        "required_sample_count": VERIFICATION_FLAT,
        "active_sample_count": 0,
        "analyzed_valid_count": 0,
        "created_by_user_id": user_id,
        "approved_by_user_id": None,
        "status": "DRAFT",
    }
    stamp_new(plan)
    db.sampling_plans[plan["id"]] = plan
    return plan
