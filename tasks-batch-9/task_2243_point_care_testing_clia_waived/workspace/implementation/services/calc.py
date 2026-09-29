"""Calculations (PRD 3.4, 3.9, SCAFFOLD calculations).

Every arithmetic step uses decimal.Decimal with ROUND_HALF_UP.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import db

TWO = Decimal("0.01")
ZERO_DP = Decimal("1")


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round2(value):
    return dec(value).quantize(TWO, rounding=ROUND_HALF_UP)


def round0(value):
    return dec(value).quantize(ZERO_DP, rounding=ROUND_HALF_UP)


def num2(value):
    """Serialise a 2-decimal quantity as a JSON number."""
    return float(round2(value))


# --------------------------------------------------------------------------
# qc_run_result / temperature_disposition — both bounds inclusive
# --------------------------------------------------------------------------

def qc_run_result(measured_value, expected_min, expected_max):
    value = dec(measured_value)
    if dec(expected_min) <= value <= dec(expected_max):
        return "PASS"
    return "FAIL"


def temperature_disposition(reading_c, min_temp_c, max_temp_c):
    value = dec(reading_c)
    if dec(min_temp_c) <= value <= dec(max_temp_c):
        return "IN_RANGE"
    return "OUT_OF_RANGE"


# --------------------------------------------------------------------------
# deficiency_weight
# --------------------------------------------------------------------------

SEVERITY_BASE = {
    "CONDITION_LEVEL": Decimal("8.0"),
    "STANDARD_LEVEL": Decimal("3.0"),
    "ADVISORY": Decimal("1.0"),
}


def repeat_multiplier(finding):
    """2.0 when an earlier CLOSED finding of the same category exists at the site."""
    for other in db.all_rows("findings"):
        if other["id"] == finding["id"]:
            continue
        if other["site_id"] != finding["site_id"]:
            continue
        if other["category"] != finding["category"]:
            continue
        if other["status"] != "CLOSED":
            continue
        if db.earlier(other, finding):
            return Decimal("2.0")
    return Decimal("1.0")


def deficiency_weight(severity, multiplier):
    return round2(SEVERITY_BASE[severity] * dec(multiplier))


# --------------------------------------------------------------------------
# device_qc_compliance_rate
# --------------------------------------------------------------------------

def _window(device):
    created = clock.parse_date(device["created_at"][:10])
    end = clock.today()
    start = end - timedelta(days=30)
    if created is not None and created > start:
        start = created
    return start, end


def compliance_rates(device):
    """Return (calendar_rate, day_of_use_rate, use_day_count) as Decimals/int."""
    start, end = _window(device)
    if end < start:
        return round2(100), round2(100), 0

    level1 = set()
    level2 = set()
    for run in db.all_rows("qc_runs"):
        if run["device_id"] != device["id"] or run["result"] != "PASS":
            continue
        day = clock.parse_date(run["performed_at"][:10])
        if day is None:
            continue
        if run["control_level"] == "LEVEL_1":
            level1.add(day)
        elif run["control_level"] == "LEVEL_2":
            level2.add(day)
    covered = {d for d in (level1 & level2) if start <= d <= end}

    used = set()
    for result in db.all_rows("results"):
        if result["device_id"] != device["id"]:
            continue
        day = clock.parse_date(result["created_at"][:10])
        if day is not None and start <= day <= end:
            used.add(day)

    numerator = len(covered)
    calendar_den = (end - start).days + 1
    day_of_use_den = len(used)

    calendar = _rate(numerator, calendar_den)
    day_of_use = _rate(numerator, day_of_use_den)
    return calendar, day_of_use, day_of_use_den


def _rate(numerator, denominator):
    if denominator == 0:
        return round2(100)
    return round2(Decimal(100) * Decimal(numerator) / Decimal(denominator))


def two_level_pass_day(device):
    """Latest calendar day carrying a PASS on both control levels."""
    level1 = set()
    level2 = set()
    for run in db.all_rows("qc_runs"):
        if run["device_id"] != device["id"] or run["result"] != "PASS":
            continue
        day = clock.parse_date(run["performed_at"][:10])
        if day is None:
            continue
        if run["control_level"] == "LEVEL_1":
            level1.add(day)
        elif run["control_level"] == "LEVEL_2":
            level2.add(day)
    both = level1 & level2
    if not both:
        return None
    return max(both)


# --------------------------------------------------------------------------
# site_qc_compliance_index
# --------------------------------------------------------------------------

def site_qc_compliance_index(site):
    eligible = [d for d in db.rows("devices")
                if d["site_id"] == site["id"] and d["status"] != "RETIRED"]
    if not eligible:
        return round2(100)
    # STEP 1 — round each per-device day-of-use rate to a whole percent.
    rounded = [round0(d["qc_compliance_rate_day_of_use"]) for d in eligible]
    # STEP 2 — average the whole numbers, then round to two decimals.
    total = sum(rounded, Decimal(0))
    return round2(total / Decimal(len(rounded)))


# --------------------------------------------------------------------------
# site_inspection_readiness_score
# --------------------------------------------------------------------------

OPEN_WEIGHT_STATUSES = ("OPEN", "CORRECTION_SUBMITTED", "CORRECTION_REJECTED")


def open_deficiency_weight(site_id, basis="AS_OF_ACTUAL"):
    today = clock.today()
    total = Decimal("0")
    for finding in db.rows("findings"):
        if finding["site_id"] != site_id:
            continue
        if finding["status"] not in OPEN_WEIGHT_STATUSES:
            continue
        if basis == "PRE_SURVEY_PROJECTED" and finding["status"] == "CORRECTION_SUBMITTED":
            due = clock.parse_date(finding.get("correction_due_date"))
            if due is not None and due >= today:
                continue
        total += dec(finding["weight"] or 0)
    return round2(total)


def pt_unsuccessful_count(site_id, basis="AS_OF_ACTUAL"):
    excluded = {"INVESTIGATION_ACCEPTED"}
    if basis == "PRE_SURVEY_PROJECTED":
        excluded.add("INVESTIGATION_SUBMITTED")
    enrollment_ids = {e["id"] for e in db.rows("enrollments")
                      if e["site_id"] == site_id}
    count = 0
    for event in db.rows("pt_events"):
        if event["enrollment_id"] not in enrollment_ids:
            continue
        if event["outcome"] != "FAIL":
            continue
        if event["status"] in excluded:
            continue
        count += 1
    return count


def readiness(site, basis="AS_OF_ACTUAL"):
    weight = open_deficiency_weight(site["id"], basis)
    pt_count = pt_unsuccessful_count(site["id"], basis)
    index = dec(site["site_qc_compliance_index"])

    deficiency_penalty = min(Decimal("50.0"), round2(weight * Decimal("2.5")))

    total_ops = int(site["total_operator_count"] or 0)
    lapsed = int(site["lapsed_or_locked_operator_count"] or 0)
    gap = Decimal("100.0") * Decimal(lapsed) / Decimal(max(1, total_ops))
    competency_penalty = min(Decimal("25.0"), round2(gap * Decimal("0.25")))

    qc_penalty = min(Decimal("20.0"),
                     round2((Decimal("100.0") - index) * Decimal("0.40")))

    pt_unit = Decimal("6") if site["complexity_scope"] == "MODERATE" else Decimal("3")
    pt_penalty = min(Decimal("18.0"), Decimal(pt_count) * pt_unit)

    raw = (Decimal("100.0") - deficiency_penalty - competency_penalty
           - qc_penalty - pt_penalty)
    score = max(Decimal("0.0"), round2(raw))

    return {
        "basis": basis,
        "score": float(score),
        "deficiency_penalty": float(round2(deficiency_penalty)),
        "competency_penalty": float(round2(competency_penalty)),
        "qc_penalty": float(round2(qc_penalty)),
        "pt_penalty": float(round2(pt_penalty)),
        "open_deficiency_weight": float(round2(weight)),
        "pt_unsuccessful_count": pt_count,
        "site_qc_compliance_index": float(round2(index)),
    }


# --------------------------------------------------------------------------
# pt_event_outcome
# --------------------------------------------------------------------------

def pt_event_outcome(score_pct):
    return "PASS" if dec(score_pct) >= Decimal("80.00") else "FAIL"


def fail_count_last_three(enrollment_id):
    graded = [e for e in db.all_rows("pt_events")
              if e["enrollment_id"] == enrollment_id and e["outcome"] is not None]
    graded.sort(key=lambda e: (e["graded_on"] or "", e["created_at"],
                               e["shipment_number"]))
    window = graded[-3:]
    return sum(1 for e in window if e["outcome"] == "FAIL")


def graded_event_count(enrollment_id):
    return sum(1 for e in db.all_rows("pt_events")
               if e["enrollment_id"] == enrollment_id and e["outcome"] is not None)


# --------------------------------------------------------------------------
# certificate_coverage_overlap (closed-closed) / competency_window_overlap
# (half-open)
# --------------------------------------------------------------------------

def coverage_collides(site_id, start, end):
    for coverage in db.rows("coverages"):
        if coverage["site_id"] != site_id:
            continue
        certificate = db.get("certificates", coverage["certificate_id"])
        if certificate is None or certificate["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        other_start = clock.parse_date(coverage["coverage_start"])
        other_end = clock.parse_date(coverage["coverage_end"])
        if other_start is None or other_end is None:
            continue
        # Closed-closed: touching endpoints collide.
        if start <= other_end and other_start <= end:
            return True
    return False


def assessment_collides(operator_id, device_model, effective_date, expires_at):
    for assessment in db.rows("assessments"):
        if assessment["operator_id"] != operator_id:
            continue
        if assessment["device_model"] != device_model:
            continue
        if assessment["status"] != "APPROVED":
            continue
        other_start = clock.parse_date(assessment["effective_date"])
        other_end = clock.parse_date(assessment["expires_at"])
        if other_start is None or other_end is None:
            continue
        # Half-open: touching endpoints do not collide.
        if effective_date < other_end and other_start < expires_at:
            return True
    return False
