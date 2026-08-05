"""The thirteen calculation rules (PRD 3.x / SCAFFOLD 1.3).

Boundary conventions are deliberately NOT shared between rules: PRD 2.10 runs
three at once and each is written out at its own site here.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from . import constants, timeutil


# ---------------------------------------------------------------- rounding --

def round_half_up(value, places=0):
    """Half-up rounding; a value exactly at the half rounds away from zero."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exp = Decimal(1).scaleb(-places)
    return value.quantize(exp, rounding=ROUND_HALF_UP)


def cents(value):
    return int(round_half_up(value, 0))


def as_decimal(value):
    return Decimal(str(value))


# --------------------------------------------- 12. eligibility_coverage -----
# The coverage span is CLOSED AT BOTH ENDS (PRD 2.10 / 3.3).  A member is
# still covered ON the termination date.

def coverage_covers(record, d):
    eff = timeutil.parse_date(record.get("effective_date"))
    if eff is None or d is None:
        return False
    if d < eff:
        return False
    term = timeutil.parse_date(record.get("termination_date")) if record.get("termination_date") else None
    if term is not None and d > term:
        return False
    return True


def coverage_status_of(record, clock_date):
    eff = timeutil.parse_date(record.get("effective_date"))
    term_raw = record.get("termination_date")
    term = timeutil.parse_date(term_raw) if term_raw else None
    if eff is not None and clock_date < eff:
        return "FUTURE"
    if term is not None and clock_date > term:
        return "EXPIRED"
    return "EFFECTIVE"


def spans_overlap(a_start, a_end, b_start, b_end):
    """Closed-interval overlap; a null end means unbounded into the future."""
    if a_end is not None and b_start > a_end:
        return False
    if b_end is not None and a_start > b_end:
        return False
    return True


# ------------------------------------------------- 1. health_risk_score -----

def _bp_points(systolic, diastolic):
    if (systolic is not None and systolic >= constants.BP_STAGE2_SYSTOLIC_MIN) or (
        diastolic is not None and diastolic >= constants.BP_STAGE2_DIASTOLIC_MIN
    ):
        return 3
    stage1_sys = (
        systolic is not None
        and constants.BP_STAGE1_SYSTOLIC_MIN <= systolic <= constants.BP_STAGE1_SYSTOLIC_MAX
    )
    stage1_dia = (
        diastolic is not None
        and constants.BP_STAGE1_DIASTOLIC_MIN <= diastolic <= constants.BP_STAGE1_DIASTOLIC_MAX
    )
    if stage1_sys or stage1_dia:
        return 2
    elevated = (
        systolic is not None
        and constants.BP_ELEVATED_SYSTOLIC_MIN <= systolic <= constants.BP_ELEVATED_SYSTOLIC_MAX
    )
    if elevated and diastolic is not None and diastolic < constants.BP_STAGE1_DIASTOLIC_MIN:
        return 1
    return 0


def _bmi_points(bmi):
    if bmi is None:
        return 0
    if bmi >= constants.BMI_OBESE2_MIN:
        return 3
    if bmi >= constants.BMI_OBESE1_MIN:
        return 2
    if bmi >= constants.BMI_OVERWEIGHT_MIN:
        return 1
    return 0


def _a1c_points(a1c):
    if a1c is None:
        return 0
    if a1c >= constants.A1C_DIABETES_MIN:
        return 3
    if a1c >= constants.A1C_PREDIABETES_MIN:
        return 1
    return 0


def _ldl_points(ldl):
    if ldl is None:
        return 0
    if ldl >= constants.LDL_HIGH_MIN:
        return 2
    if ldl >= constants.LDL_BORDERLINE_MIN:
        return 1
    return 0


def health_risk_score(source_type, systolic, diastolic, bmi, a1c, ldl,
                      cotinine, self_reported_tobacco):
    """Returns risk_points_raw, risk_points_total, risk_band,
    outcome_standard_met, outcome_credit_status."""
    bp = _bp_points(systolic, diastolic)
    bmi_p = _bmi_points(bmi)
    a1c_p = _a1c_points(a1c)
    ldl_p = _ldl_points(ldl)

    if source_type == "CLINIC_MEASURED":
        tobacco_p = 3 if (cotinine is not None and cotinine >= constants.COTININE_POSITIVE_MIN) else 0
        missing_p = 0
    else:
        tobacco_p = constants.TOBACCO_SELF_REPORT_POINTS if self_reported_tobacco is True else 0
        missing_p = 0
        # The blood-pressure pair counts as ONE metric and is absent only when
        # both members are omitted (PRD 3.6).
        if systolic is None and diastolic is None:
            missing_p += constants.SELF_ATTEST_MISSING_METRIC_POINTS
        if a1c is None:
            missing_p += constants.SELF_ATTEST_MISSING_METRIC_POINTS
        if ldl is None:
            missing_p += constants.SELF_ATTEST_MISSING_METRIC_POINTS

    raw = bp + bmi_p + a1c_p + ldl_p + tobacco_p + missing_p

    if source_type == "CLINIC_MEASURED":
        total = raw
    else:
        total = int(
            round_half_up(
                Decimal(raw) * Decimal(constants.SELF_ATTEST_UNVERIFIED_MULTIPLIER), 0
            )
        )

    if total <= constants.RISK_BAND_LOW_MAX_POINTS:
        band = "LOW"
    elif total <= constants.RISK_BAND_MODERATE_MAX_POINTS:
        band = "MODERATE"
    else:
        band = "HIGH"

    met = total <= constants.OUTCOME_STANDARD_MAX_POINTS
    credit = "MET_DIRECT" if met else "PENDING_ALTERNATIVE"
    return raw, total, band, met, credit


# --------------------------------------------- 2. incentive_award_amount ----

def incentive_award_amount(award_type):
    return constants.AWARD_AMOUNT_BY_TYPE[award_type]


# ----------------------------------------------- 3. incentive_program_cap ---

def incentive_cap_cents(employer):
    pct = (
        constants.INCENTIVE_CAP_PCT_TOBACCO
        if employer.get("tobacco_program_enabled") is True
        else constants.INCENTIVE_CAP_PCT_STANDARD
    )
    base = Decimal(int(employer.get("annual_total_cost_of_coverage_cents") or 0))
    return int(round_half_up(base * Decimal(pct), 0))


# ------------------------------------------------ 4. vendor_contract_cost ---

def contract_gross_fee_cents(contract, billable_visit_count, staffed_hours):
    if contract["fee_model"] == "PER_VISIT":
        return int(billable_visit_count) * int(contract["per_visit_fee_cents"])
    return int(
        round_half_up(as_decimal(staffed_hours) * Decimal(int(contract["fte_hourly_rate_cents"])), 0)
    )


def contract_true_up_cents(contract, gross_fee_cents):
    return max(0, int(contract["minimum_guarantee_cents"]) - int(gross_fee_cents))


# ---------------------------------------------------- 9. referral_sla_due_at

def referral_sla_due_at(urgency, base_dt, site):
    """Dual-variant: calendar hours for EMERGENT / URGENT, site business days
    for ROUTINE (PRD 3.7)."""
    if urgency == "EMERGENT":
        return timeutil.fmt_instant(base_dt + timedelta(hours=constants.SLA_EMERGENT_HOURS))
    if urgency == "URGENT":
        return timeutil.fmt_instant(base_dt + timedelta(hours=constants.SLA_URGENT_HOURS))

    # ROUTINE -- count SLA_ROUTINE_BUSINESS_DAYS site-open days forward,
    # starting with the day AFTER the base date; the base date never counts.
    weekdays = site.get("operating_weekdays") or []
    closures = set(site.get("closure_dates") or [])
    cursor = base_dt.date()
    counted = 0
    guard = 0
    while counted < constants.SLA_ROUTINE_BUSINESS_DAYS and guard < 4000:
        guard += 1
        cursor = cursor + timedelta(days=1)
        if timeutil.iso_weekday(cursor) in weekdays and timeutil.fmt_date(cursor) not in closures:
            counted += 1
    close_minutes = timeutil.parse_hhmm(site.get("close_time_utc"))
    if close_minutes is None:
        close_minutes = 0
    return timeutil.fmt_instant(timeutil.instant_from_date_and_minutes(cursor, close_minutes))


# ------------------------------------------- 10. visit_disclosure_payload ---

def visit_disclosure_payload(visit):
    """Exact projection; `clinical_note` never appears under any status."""
    status = visit["disclosure_status"]
    if status == "FITNESS_RELEASED":
        conclusion = visit.get("fitness_conclusion")
    else:
        conclusion = None
    return {
        "visit_id": visit["id"],
        "visit_type": visit["visit_type"],
        "service_date": visit["service_date"],
        "disclosure_status": status,
        "fitness_conclusion": conclusion,
        "participation_recorded": True,
        "clinical_detail_included": False,
    }


# --------------------------------------- 11. appointment_slot_geometry ------

def slot_end(start_dt):
    return start_dt + timedelta(minutes=constants.APPOINTMENT_SLOT_MINUTES)


def inside_operating_window(site, start_dt, end_dt):
    """CLOSED containment against the site's daily window plus the weekday
    pattern (PRD 2.10 / 3.4)."""
    service_date = start_dt.date()
    if timeutil.iso_weekday(service_date) not in (site.get("operating_weekdays") or []):
        return False
    open_min = timeutil.parse_hhmm(site.get("open_time_utc"))
    close_min = timeutil.parse_hhmm(site.get("close_time_utc"))
    if open_min is None or close_min is None:
        return False
    start_min = start_dt.hour * 60 + start_dt.minute
    day_offset = (end_dt.date() - service_date).days
    end_min = end_dt.hour * 60 + end_dt.minute + day_offset * 1440
    return start_min >= open_min and end_min <= close_min


def shift_closed_contains(shift_start_dt, shift_end_dt, start_dt, end_dt):
    """CLOSED containment: an appointment ending exactly at shift_end IS
    covered (PRD 2.10 / 3.2)."""
    return shift_start_dt <= start_dt and shift_end_dt >= end_dt


def half_open_overlap(a_start, a_end, b_start, b_end):
    """HALF-OPEN pairwise overlap with zero buffer: two appointments that
    merely touch do NOT collide (PRD 2.10 / 3.4)."""
    return a_start < b_end and b_start < a_end


# ------------------------------------------ 13. quota_contract_selection ----

def select_quota_contract(contracts, site_id, employer_id):
    """Waterfall selector with all four elements pinned (PRD 3.4)."""
    eligible = [
        c
        for c in contracts
        if c["site_id"] == site_id
        and c["employer_id"] == employer_id
        and c["status"] in ("ACTIVE", "TRUED_UP")
        and int(c["quota_visits_consumed"]) < int(c["quota_visits_total"])
    ]
    if not eligible:
        return None
    eligible.sort(key=lambda c: (int(c["quota_visits_remaining"]), c["created_at"], c["_seq"]))
    return eligible[0]
