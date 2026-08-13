"""Calculation rules from scaffold §1.3. Money: integer cents with
round-half-up. Dyno scoring: 2dp round-half-up per penalty, then sum."""

from decimal import Decimal, ROUND_HALF_UP


# --- core_provisional_credit ---
PROVISIONAL_CREDIT_FACTOR = Decimal("0.8")


def round_half_up_int(value):
    """Round a Decimal to 0 decimal places, ROUND_HALF_UP, return int."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def provisional_credit(deposit_cents):
    return round_half_up_int(Decimal(deposit_cents) * PROVISIONAL_CREDIT_FACTOR)


# --- core_grade_and_credit ---
FINDING_WEIGHTS = {
    "TORQUE_CONVERTER_MISSING": 20,
    "VALVE_BODY_MISSING": 25,
    "SENSOR_HARNESS_MISSING": 10,
    "BELL_HOUSING_DAMAGED": 15,
    "PAN_MISSING": 5,
}
FINDING_ENUM = set(FINDING_WEIGHTS.keys())
GRADE_A_MAX = 5
GRADE_B_MAX = 15
GRADE_C_MAX = 30
GRADE_MULTIPLIER = {
    "A": Decimal("1.0"),
    "B": Decimal("0.75"),
    "C": Decimal("0.5"),
}
ON_TIME_DAYS = 30
LATE_CUTOFF_DAYS = 45
LATE_CREDIT_FACTOR = Decimal("0.75")


def compute_grade(case_cracked, findings):
    deduction_score = sum(FINDING_WEIGHTS[f] for f in findings)
    if case_cracked:
        return deduction_score, "REJECTED"
    if deduction_score <= GRADE_A_MAX:
        grade = "A"
    elif deduction_score <= GRADE_B_MAX:
        grade = "B"
    elif deduction_score <= GRADE_C_MAX:
        grade = "C"
    else:
        grade = "REJECTED"
    return deduction_score, grade


def compute_final_credit(deposit_cents, grade, days_late):
    """Returns (final_credit_cents, forfeited_cents, invoice_status)."""
    if days_late <= ON_TIME_DAYS:
        late_factor = Decimal("1.0")
    elif days_late <= LATE_CUTOFF_DAYS:
        late_factor = LATE_CREDIT_FACTOR
    else:
        late_factor = None  # forfeit

    if grade == "REJECTED" or late_factor is None:
        return 0, deposit_cents, "FORFEITED"
    raw = Decimal(deposit_cents) * GRADE_MULTIPLIER[grade] * late_factor
    credit = round_half_up_int(raw)
    forfeited = deposit_cents - credit
    status = "SETTLED_FULL" if credit == deposit_cents else "SETTLED_PARTIAL"
    return credit, forfeited, status


# --- dyno_shift_quality_score ---
PENALTY_PER_KPA = Decimal("2.0")
PASS_MIN = Decimal("90.00")
MARGINAL_MIN = Decimal("80.00")
MAX_DYNO_ATTEMPTS = 3


def compute_dyno_score(gear_pressures, dyno_targets):
    """Per-gear penalty rounded to 2dp FIRST, then summed, then 100 - sum
    rounded to 2dp, floored at 0. Returns (score_float, verdict)."""
    targets = sorted(dyno_targets, key=lambda t: t["gear"])
    penalties = []
    for i, t in enumerate(targets):
        measured = Decimal(str(gear_pressures[i]))
        target = Decimal(str(t["target_pressure_kpa"]))
        diff = abs(measured - target)
        penalty = round_half_up_2dp(diff * PENALTY_PER_KPA)
        penalties.append(penalty)
    total = sum(penalties, Decimal("0"))
    score = round_half_up_2dp(Decimal("100") - total)
    if score < 0:
        score = Decimal("0.00")
    if score >= PASS_MIN:
        verdict = "PASS"
    elif score >= MARGINAL_MIN:
        verdict = "MARGINAL"
    else:
        verdict = "FAIL"
    return float(score), verdict


# --- warranty_labor_allowance ---
ROUTING_VALUE_THRESHOLD_CENTS = 50000


def compute_labor_allowance(claim, pinned_spec):
    """BOOK_HOURS: hours = flat_rate_hours.
    ACTUAL_HOURS: hours = min(claimed, flat_rate_hours).
    allowance = round_half_up(hours * rate, 0); capped at labor_cap_cents."""
    flat = Decimal(str(pinned_spec["flat_rate_hours"]))
    if claim["allowance_policy"] == "BOOK_HOURS":
        hours = flat
    else:  # ACTUAL_HOURS
        claimed = Decimal(str(claim["claimed_labor_hours"]))
        hours = min(claimed, flat)
    raw = hours * Decimal(claim["installer_labor_rate_cents"])
    allowance = round_half_up_int(raw)
    cap = pinned_spec["labor_cap_cents"]
    return min(allowance, cap)


def compute_routing(failure_code, labor_allowance_cents):
    if failure_code == "ELECTRICAL_TCM":
        routing = "RETURN_TO_DISTRIBUTOR"
    elif labor_allowance_cents >= ROUTING_VALUE_THRESHOLD_CENTS:
        routing = "RETURN_TO_PLANT"
    else:
        routing = "LOCAL_SCRAP"
    return routing, (routing != "LOCAL_SCRAP")
