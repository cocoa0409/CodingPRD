"""The calculation rules of PRD sections 3.2, 3.6-3.12.

Every money figure is computed with ``decimal.Decimal`` and rounded half-up;
no float ever touches a monetary or percentage value.
"""

from decimal import Decimal, ROUND_HALF_UP

import clock
import config
import store


def round_half_up(value, places):
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def round_cents(value):
    return int(round_half_up(value, 0))


# --------------------------------------------------------------------------
# fpl_percent_and_discount_tier  (PRD 3.2)
# --------------------------------------------------------------------------
def fpl_percent_and_tier(household_income_annual_cents, household_size):
    threshold = Decimal(config.FPL_BASE_ANNUAL_CENTS) + (
        Decimal(household_size - 1) * Decimal(config.FPL_INCREMENT_PER_ADDITIONAL_PERSON_CENTS)
    )
    if threshold == 0:  # pragma: no cover - household_size >= 1 keeps this positive
        raw = Decimal(0)
    else:
        raw = (Decimal(household_income_annual_cents) * Decimal(100)) / threshold
    # STEP 1: round first, to 2 decimal places.
    percent = round_half_up(raw, 2)
    # STEP 2: band the ROUNDED value.
    if percent <= Decimal(config.TIER_A_MAX_FPL_PERCENT):
        tier = "TIER_A"
    elif percent <= Decimal(config.TIER_B_MAX_FPL_PERCENT):
        tier = "TIER_B"
    elif percent <= Decimal(config.TIER_C_MAX_FPL_PERCENT):
        tier = "TIER_C"
    elif percent <= Decimal(config.TIER_D_MAX_FPL_PERCENT):
        tier = "TIER_D"
    else:
        tier = "TIER_E"
    return percent, tier


def discount_fraction(tier):
    return Decimal(config.DISCOUNT_PCT[tier])


# --------------------------------------------------------------------------
# charge_patient_responsibility  (PRD 3.10)
# --------------------------------------------------------------------------
def provisional_responsibility(charge):
    """Variant PROVISIONAL_GROSS_FIRST."""
    if charge["service_category"] in config.NO_CHARGE_SERVICE_CATEGORIES:
        base = Decimal(0)
    elif charge["payer_route"] == "MEDICAID":
        base = Decimal(0)
    elif charge["payer_route"] == "PRIVATE_INSURANCE":
        base = Decimal(config.PRIVATE_COPAY_CENTS)
    else:  # SELF_PAY
        base = Decimal(charge["gross_amount_cents"])
    pct = discount_fraction(charge["discount_tier_snapshot"])
    return round_cents(base * (Decimal(1) - pct))


def final_responsibility(charge, payer_paid_amount_cents):
    """Variant FINAL_NET_OF_PAYER."""
    residual = Decimal(max(0, charge["gross_amount_cents"] - payer_paid_amount_cents))
    if charge["service_category"] in config.NO_CHARGE_SERVICE_CATEGORIES:
        base = Decimal(0)
    elif charge["payer_route"] == "MEDICAID":
        base = Decimal(0)
    elif charge["payer_route"] == "PRIVATE_INSURANCE":
        base = residual
    else:  # SELF_PAY
        base = Decimal(charge["gross_amount_cents"])
    pct = discount_fraction(charge["discount_tier_snapshot"])
    return round_cents(base * (Decimal(1) - pct))


def unfloored_amount(charge):
    if charge["final_patient_responsibility_cents"] is not None:
        return charge["final_patient_responsibility_cents"]
    return charge["provisional_patient_responsibility_cents"]


# --------------------------------------------------------------------------
# screening_band_outcome  (PRD 3.8)
# --------------------------------------------------------------------------
def screening_outcome(instrument, numeric_result):
    value = Decimal(str(numeric_result))
    if instrument == "VISION":
        refer = value >= Decimal(config.VISION_REFER_DENOMINATOR_MIN)
    elif instrument == "HEARING":
        refer = value > Decimal(config.HEARING_REFER_DB_EXCLUSIVE)
    elif instrument == "DENTAL":
        refer = value >= Decimal(config.DENTAL_REFER_CARIES_MIN)
    elif instrument == "BMI":
        refer = value < Decimal(config.BMI_REFER_PERCENTILE_LOW_EXCLUSIVE) or value >= Decimal(
            config.BMI_REFER_PERCENTILE_HIGH_INCLUSIVE
        )
    elif instrument == "BEHAVIORAL":
        refer = value >= Decimal(config.BEHAVIORAL_REFER_SCORE_MIN)
    else:  # pragma: no cover - enum guarded at rung 6
        refer = False
    outcome = "REFER" if refer else "PASS"
    band = "ABNORMAL" if refer else "NORMAL"
    return outcome, band


# --------------------------------------------------------------------------
# clearance_validity_window  (PRD 3.9)
# --------------------------------------------------------------------------
def clearance_validity(outcome, determination_date, school_year):
    days = config.CLEARANCE_VALIDITY_DAYS.get(outcome)
    if days is None:
        return None, None
    unrestricted = clock.add_days(determination_date, days)
    year_end = clock.parse_date(clock.school_year_end_date(school_year))
    operative = unrestricted if unrestricted <= year_end else year_end
    return clock.format_date(unrestricted), clock.format_date(operative)


# --------------------------------------------------------------------------
# immunization_dose_validity  (PRD 3.7)
# --------------------------------------------------------------------------
def find_predecessor(student_id, series_code, dose_number):
    for dose in store.all_rows("doses"):
        if (
            dose["student_id"] == student_id
            and dose["series_code"] == series_code
            and dose["dose_number"] == dose_number - 1
            and dose["status"] == "VALID"
        ):
            return dose
    return None


def dose_validity(student, series_code, dose_number, administered_date):
    """Returns (earliest_valid_date, strict_earliest_valid_date, status, invalid_reason).

    All dates are ``YYYY-MM-DD`` strings; the two computed dates are None only
    when the predecessor is missing (the caller then keeps the stored values).
    """
    if dose_number == 1:
        min_days = config.SERIES_DOSE1_MIN_AGE_DAYS[series_code]
        born = clock.parse_date(student["date_of_birth"])
        strict = clock.add_days(born, min_days)
        reason_on_failure = "MIN_AGE_NOT_MET"
    else:
        predecessor = find_predecessor(student["id"], series_code, dose_number)
        if predecessor is None:
            return None, None, "INVALID_TOO_EARLY", "PREDECESSOR_VOIDED"
        interval = config.SERIES_INTERVAL_DAYS[(series_code, dose_number)]
        strict = clock.add_days(clock.parse_date(predecessor["administered_date"]), interval)
        reason_on_failure = "MIN_INTERVAL_NOT_MET"
    earliest = clock.add_days(strict, -config.IMMUNIZATION_GRACE_DAYS)
    given = clock.parse_date(administered_date)
    if given >= earliest:
        status, reason = "VALID", None
    else:
        status, reason = "INVALID_TOO_EARLY", reason_on_failure
    return clock.format_date(earliest), clock.format_date(strict), status, reason


# --------------------------------------------------------------------------
# immunization_compliance_status  (PRD 3.7)
# --------------------------------------------------------------------------
def student_doses(student_id):
    return [d for d in store.all_rows("doses") if d["student_id"] == student_id]


def valid_count(student_id, series_code):
    return len(
        [
            d
            for d in store.DB["doses"].values()
            if d["student_id"] == student_id
            and d["series_code"] == series_code
            and d["status"] == "VALID"
        ]
    )


def strict_valid_count(student_id, series_code):
    total = 0
    for dose in store.DB["doses"].values():
        if dose["student_id"] != student_id or dose["series_code"] != series_code:
            continue
        if dose["status"] != "VALID":
            continue
        strict = dose.get("strict_earliest_valid_date")
        if strict is None:
            continue
        if clock.parse_date(dose["administered_date"]) >= clock.parse_date(strict):
            total += 1
    return total


def active_enrollment(student_id):
    for enrollment in store.all_rows("enrollments"):
        if enrollment["student_id"] == student_id and enrollment["status"] == "ACTIVE":
            return enrollment
    return None


def compliance_status(student):
    """GRACE_COUNTING variant — the operative posture written to the student."""
    if student["immunization_exemption_type"] != "NONE":
        return "COMPLIANT"
    hepb = valid_count(student["id"], "HEPB")
    mmr = valid_count(student["id"], "MMR")
    if hepb >= config.SERIES_REQUIRED_DOSES["HEPB"] and mmr >= config.SERIES_REQUIRED_DOSES["MMR"]:
        return "COMPLIANT"
    enrollment = active_enrollment(student["id"])
    if enrollment is not None and enrollment.get("activated_at"):
        activated = clock.parse_datetime(enrollment["activated_at"]).date()
        deadline = clock.add_days(activated, config.PROVISIONAL_WINDOW_DAYS)
        if clock.now_date() <= deadline and hepb >= 1 and mmr >= 1:
            return "PROVISIONAL"
    return "NON_COMPLIANT"


def strict_compliant(student):
    """STRICT_COUNTING variant — report only; grace withdrawn, exemptions ignored."""
    return (
        strict_valid_count(student["id"], "HEPB") >= config.SERIES_REQUIRED_DOSES["HEPB"]
        and strict_valid_count(student["id"], "MMR") >= config.SERIES_REQUIRED_DOSES["MMR"]
    )


# --------------------------------------------------------------------------
# notification_guardian_selection  (PRD 3.2)
# --------------------------------------------------------------------------
def select_guardian(student_id):
    candidates = [g for g in store.DB["guardians"].values() if g["student_id"] == student_id]
    if not candidates:
        return None
    candidates.sort(key=lambda g: (0 if g["is_primary"] else 1, g["created_at"], g["_seq"]))
    return candidates[0]


# --------------------------------------------------------------------------
# school_booked_minutes_total  (PRD 2.10 / 3.6)
# --------------------------------------------------------------------------
def booked_minutes(school_id):
    return sum(
        s["duration_minutes"]
        for s in store.DB["sessions"].values()
        if s["school_id"] == school_id and s["status"] in ("SCHEDULED", "COMPLETED")
    )


# --------------------------------------------------------------------------
# telehealth_resource_conflict  (PRD 3.6)
# --------------------------------------------------------------------------
def clinician_conflict(clinician_id, start_dt, end_dt, exclude_session_id=None):
    buffer_minutes = config.TELEHEALTH_TURNAROUND_BUFFER_MINUTES
    for session in store.DB["sessions"].values():
        if session["id"] == exclude_session_id:
            continue
        if session["clinician_id"] != clinician_id:
            continue
        if session["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        s_start = clock.parse_datetime(session["start_at"])
        s_end = clock.parse_datetime(session["end_at"])
        if start_dt < clock.add_minutes(s_end, buffer_minutes) and s_start < clock.add_minutes(
            end_dt, buffer_minutes
        ):
            return True
    return False


def school_overlap_count(school_id, start_dt, end_dt, exclude_session_id=None):
    count = 0
    for session in store.DB["sessions"].values():
        if session["id"] == exclude_session_id:
            continue
        if session["school_id"] != school_id:
            continue
        if session["status"] not in ("SCHEDULED", "COMPLETED"):
            continue
        s_start = clock.parse_datetime(session["start_at"])
        s_end = clock.parse_datetime(session["end_at"])
        if start_dt < s_end and s_start < end_dt:
            count += 1
    return count


# --------------------------------------------------------------------------
# referral_closure_rate  (PRD 3.12)
# --------------------------------------------------------------------------
def closure_rate(numerator, denominator):
    if denominator == 0:
        return 0.0
    return float(round_half_up(Decimal(numerator) / Decimal(denominator), config.REPORT_RATE_PRECISION_DP))
