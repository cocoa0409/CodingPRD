"""Calculation rules (PRD section 2.8, 3.5, 3.6, 3.7; SCAFFOLD calculations table)."""
import math
from decimal import Decimal, ROUND_HALF_UP

import db


def _round2(value):
    """Round a Decimal/number to 2 decimals, round-half-up."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def applicant_age(date_of_birth):
    """age = AGE_REFERENCE_YEAR - year(date_of_birth)."""
    birth_year = int(str(date_of_birth).split("-")[0])
    return db.AGE_REFERENCE_YEAR - birth_year


def point_balance(record, store):
    """Sum points of ACTIVE violations within the inclusive point window."""
    cur = store.current_period
    total = 0
    for v in store.violations.values():
        if v["driver_record_id"] != record["id"]:
            continue
        if v["status"] != "ACTIVE":
            continue
        if (cur - v["occurred_period"]) <= db.POINT_WINDOW_PERIODS:
            total += v["points"]
    return total


def prior_suspension_count(record, store):
    """Count this record's suspensions in SERVED or LIFTED_BY_REINSTATEMENT."""
    count = 0
    for s in store.suspensions.values():
        if s["driver_record_id"] != record["id"]:
            continue
        if s["status"] in ("SERVED", "LIFTED_BY_REINSTATEMENT"):
            count += 1
    return count


def knowledge_test_passed(record, store):
    """True while a PASSED KnowledgeTest exists within validity window of clock."""
    cur = store.current_period
    for t in store.knowledge_tests.values():
        if t["driver_record_id"] != record["id"]:
            continue
        if t["status"] != "PASSED":
            continue
        # graded_period is the clock period at which it was graded PASSED.
        graded = t.get("graded_period")
        if graded is None:
            continue
        if (cur - graded) <= db.KNOWLEDGE_VALIDITY_PERIODS:
            return True
    return False


def score_pct(correct_answers, total_questions):
    """round(correct/total*100, 2) half-up."""
    if total_questions == 0:
        return float(_round2(0))
    val = Decimal(correct_answers) / Decimal(total_questions) * Decimal(100)
    return float(_round2(val))


def weighted_score(maneuver_scores, value_key):
    """weighted = round(sum(weight*value)/sum(weight), 2) half-up."""
    num = Decimal(0)
    den = Decimal(0)
    for m in maneuver_scores:
        weight = Decimal(str(m["weight"]))
        value = Decimal(str(m[value_key]))
        num += weight * value
        den += weight
    if den == 0:
        return float(_round2(0))
    return float(_round2(num / den))


def suspension_duration(point_balance_at_start, prior_count):
    """Tiered base days scaled by repeat-offender multiplier, floored."""
    if point_balance_at_start >= db.TIER3_POINTS:
        base_days = db.TIER3_DAYS
    elif point_balance_at_start >= db.TIER2_POINTS:
        base_days = db.TIER2_DAYS
    elif point_balance_at_start >= db.TIER1_POINTS:
        base_days = db.TIER1_DAYS
    else:
        base_days = 0
    mult = min(1 + db.MULT_STEP * prior_count, db.MULT_CAP)
    return int(math.floor(base_days * mult))


def renewal_fee(license_class, age, is_real_id, current_period, prior_expiry_period):
    """Integer-cent fee; min/max bounds applied to components before sum."""
    base = db.CLASS_BASE_FEE_CENTS[license_class]
    senior_discount = db.SENIOR_DISCOUNT_CENTS if age >= db.SENIOR_AGE else 0
    real_id_surcharge = db.REAL_ID_SURCHARGE_CENTS if is_real_id else 0
    if prior_expiry_period is None:
        days_late = 0
    else:
        days_late = max(current_period - prior_expiry_period, 0)
    late_penalty = min(days_late * db.LATE_PER_DAY_CENTS, db.LATE_CAP_CENTS)
    fee = max(base - senior_discount, 0) + real_id_surcharge + late_penalty
    return fee


def reinstatement_fee(point_balance_at_reinstatement):
    """Per-component round-half-up to 2 decimals THEN sum (order pinned)."""
    base_component = _round2(db.BASE_REINSTATEMENT_DOLLARS)
    point_component = _round2(
        Decimal(point_balance_at_reinstatement) * Decimal(db.PER_POINT_DOLLARS)
    )
    admin_component = _round2(
        Decimal(db.ADMIN_PCT) * (base_component + point_component)
    )
    total = _round2(base_component + point_component + admin_component)
    return float(total)
