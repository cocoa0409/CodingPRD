"""The eleven declared calculations. All rounding is ROUND_HALF_UP."""

from decimal import Decimal, ROUND_HALF_UP

import clock
from constants import (
    AUDIT_CONDITIONAL_MIN,
    AUDIT_PASS_MIN,
    BASE_FEE_CENTS,
    BASE_LOTS_PER_YEAR,
    CATEGORY_MULTIPLIER,
    CERTIFICATE_TERM_DAYS,
    DAYS_PER_YEAR,
    ESCALATION_PENALTY,
    GOOD_STANDING_MIN,
    INGREDIENT_RISK_THRESHOLD_PPM,
    MIN_EXCLUSION_DAYS,
    MIN_LOTS_PER_YEAR,
    NO_SHARED_EQUIPMENT_THRESHOLD_PPM,
    OPERATIONS_THRESHOLD_PPM,
    PERFECT_SCORE,
    PER_INGREDIENT_FEE_CENTS,
    PROGRAM_MAX_THRESHOLD_PPM,
    PROGRAM_MIN_THRESHOLD_PPM,
    RECALL_LOOKBACK_DAYS,
    RECALL_SCOPE_LOT_COUNT,
    RISK_WEIGHT,
    SAME_LINE_HIGH_RISK_PENALTY_PPM,
    SEVERITY_POINTS,
    SHARED_EQUIPMENT_FEE_CENTS,
    SHARED_EQUIPMENT_THRESHOLD_PPM,
    SUBSTANTIATED_COMPLAINT_PENALTY,
    SURVEILLANCE_GRACE_DAYS,
    SUSPENDED_CERT_PENALTY,
    TIER_THRESHOLD_PPM,
    VERIFIED_CA_RELIEF,
    WATCH_MIN,
)

ZERO = Decimal("0")


def half_up(value):
    """Round a Decimal to the nearest integer, halves away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(value):
    return Decimal(str(value))


# ------------------------------------------------------------ 1. threshold
def threshold_standard(requested_tier, ingredients, facility):
    """Most protective of five independent caps, then the same-line penalty."""
    program_cap = PROGRAM_MAX_THRESHOLD_PPM
    tier_cap = TIER_THRESHOLD_PPM[requested_tier]
    if ingredients:
        ingredient_cap = min(
            INGREDIENT_RISK_THRESHOLD_PPM[i["risk_class"]] for i in ingredients
        )
    else:
        ingredient_cap = PROGRAM_MAX_THRESHOLD_PPM
    equipment_cap = (
        SHARED_EQUIPMENT_THRESHOLD_PPM
        if facility["shared_equipment_present"]
        else NO_SHARED_EQUIPMENT_THRESHOLD_PPM
    )
    operations_cap = OPERATIONS_THRESHOLD_PPM[facility["gluten_containing_operations"]]
    raw = min(program_cap, tier_cap, ingredient_cap, equipment_cap, operations_cap)
    if facility["gluten_containing_operations"] == "SAME_LINE" and any(
        i["risk_class"] == "HIGH_RISK_GRAIN" for i in ingredients
    ):
        raw = raw - SAME_LINE_HIGH_RISK_PENALTY_PPM
    return max(PROGRAM_MIN_THRESHOLD_PPM, raw)


# ------------------------------------------------------------ 2. sampling plan
def _threshold_multiplier(threshold_ppm):
    t = dec(threshold_ppm)
    if t <= 5:
        return Decimal("2.0")
    if t <= 10:
        return Decimal("1.5")
    return Decimal("1.0")


def sampling_plan(threshold_ppm, lines):
    """`lines` is a list of (ingredient_row, product_ingredient_row) pairs."""
    multiplier = _threshold_multiplier(threshold_ppm)
    total = 0
    for ingredient, link in lines:
        weight = dec(RISK_WEIGHT[ingredient["risk_class"]])
        inclusion_factor = (
            Decimal("0.5") if dec(link["inclusion_pct"]) < 2 else Decimal("1.0")
        )
        line_lots = half_up(
            dec(BASE_LOTS_PER_YEAR) * weight * multiplier * inclusion_factor
        )
        total += line_lots
    lots = max(MIN_LOTS_PER_YEAR, total)
    exclusion_days = max(MIN_EXCLUSION_DAYS, DAYS_PER_YEAR // lots)
    return lots, exclusion_days


# ------------------------------------------------------------ 3. fee schedule
def _surcharge_rate(base_cents):
    if base_cents < 150000:
        return Decimal("0.20")
    if base_cents < 250000:
        return Decimal("0.15")
    return Decimal("0.10")


def certification_fee(linked_ingredient_count, shared_equipment_present):
    base = (
        BASE_FEE_CENTS
        + PER_INGREDIENT_FEE_CENTS * int(linked_ingredient_count)
        + (SHARED_EQUIPMENT_FEE_CENTS if shared_equipment_present else 0)
    )
    rate = _surcharge_rate(base)
    surcharge = half_up(dec(base) * rate)
    return base, surcharge, base + surcharge


# ------------------------------------------------------------ 4. audit score
def _finding_weight(nc):
    return dec(SEVERITY_POINTS[nc["severity"]]) * dec(
        CATEGORY_MULTIPLIER[nc["category"]]
    )


def provisional_onsite_score(findings):
    """Findings created at or before onsite_end_at; relief and escalation ignored."""
    total = ZERO
    for nc in findings:
        total += _finding_weight(nc)
    return max(0, PERFECT_SCORE - half_up(total))


def final_adjudicated_score(findings):
    """Every linked finding; verified corrective action halves its weight."""
    total = ZERO
    escalations = 0
    for nc in findings:
        weight = _finding_weight(nc)
        if nc.get("ca_verified"):
            weight = weight * dec(VERIFIED_CA_RELIEF)
        total += weight
        if nc["status"] == "ESCALATED":
            escalations += 1
    return max(0, PERFECT_SCORE - half_up(total) - ESCALATION_PENALTY * escalations)


def audit_outcome(score, critical_finding_count):
    if critical_finding_count >= 1:
        return "CLOSED_FAIL"
    if score >= AUDIT_PASS_MIN:
        return "CLOSED_PASS"
    if score >= AUDIT_CONDITIONAL_MIN:
        return "CLOSED_CONDITIONAL"
    return "CLOSED_FAIL"


# ------------------------------------------------------------ 5. posture
def posture_score(nc_penalty_points, suspended_certificate_count, complaint_count):
    return max(
        0,
        PERFECT_SCORE
        - int(nc_penalty_points)
        - SUSPENDED_CERT_PENALTY * int(suspended_certificate_count)
        - SUBSTANTIATED_COMPLAINT_PENALTY * int(complaint_count),
    )


def posture_band(cycle_score):
    if cycle_score >= GOOD_STANDING_MIN:
        return "GOOD_STANDING"
    if cycle_score >= WATCH_MIN:
        return "WATCH"
    return "PROBATION"


# ------------------------------------------------------------ 8. surveillance
def surveillance_state(surveillance_due_on, now):
    if surveillance_due_on is None:
        return "CURRENT"
    grace_end = clock.add_days(surveillance_due_on, SURVEILLANCE_GRACE_DAYS)
    if now < surveillance_due_on:
        return "CURRENT"
    if now < grace_end:
        return "DUE"
    return "OVERDUE"


def certificate_term_end(issued_on):
    return clock.add_days(issued_on, CERTIFICATE_TERM_DAYS)


# ------------------------------------------------------------ 9. lot verdict
def lot_verdict(ppm_result, threshold_ppm):
    return "FAIL" if dec(ppm_result) > dec(threshold_ppm) else "PASS"


def lot_failure_severity(ppm_result, threshold_ppm):
    return "CRITICAL" if dec(ppm_result) > dec(threshold_ppm) * 2 else "MAJOR"


# ------------------------------------------------------------ 11. recall scope
def recall_scope(candidates, exposure_date, now=None):
    """Rank by sample_collected_on desc, ties by created_at asc; take three."""
    window_start = clock.add_days(exposure_date, -RECALL_LOOKBACK_DAYS)
    eligible = [
        lt
        for lt in candidates
        if lt["status"] == "RECORDED"
        and window_start <= lt["sample_collected_on"] <= exposure_date
    ]
    eligible.sort(key=lambda lt: (-lt["sample_collected_on"].timestamp(),
                                  lt["created_at"], lt["_seq"]))
    selected = eligible[:RECALL_SCOPE_LOT_COUNT]
    if not selected:
        return [], "ADVISORY_ONLY"
    if any(lt["verdict"] == "FAIL" for lt in selected):
        action = "MANDATORY_RECALL_SUPPORT"
    else:
        action = "VOLUNTARY_RECALL"
    return selected, action
