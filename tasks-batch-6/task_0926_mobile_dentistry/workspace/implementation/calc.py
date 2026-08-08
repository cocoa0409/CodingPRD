"""Calculation rules (PRD 3.x)."""

from decimal import Decimal, ROUND_HALF_UP

import clock
import store
from constants import (
    CHAIR_UTILIZATION_CAP_PCT_DEN,
    CHAIR_UTILIZATION_CAP_PCT_NUM,
    COMMERCIAL_ALLOWED_SCHEDULE_CENTS,
    COMMERCIAL_COINSURANCE_PCT,
    CONSENT_SNF_REAFFIRMATION_DAYS,
    FOLLOW_UP_EARLY_DAYS,
    FOLLOW_UP_GRACE_DAYS,
    FOLLOW_UP_ROUTINE_DAYS,
    FOLLOW_UP_URGENT_DAYS,
    FPL_BASE_ANNUAL_CENTS,
    FPL_PER_ADDITIONAL_PERSON_CENTS,
    MEDICAID_ENCOUNTER_RATE_CENTS,
    REFERRAL_SLA_SCHOOL_EARLY_BUSINESS_DAYS,
    REFERRAL_SLA_SCHOOL_ROUTINE_BUSINESS_DAYS,
    REFERRAL_SLA_SCHOOL_URGENT_BUSINESS_DAYS,
    REFERRAL_SLA_SNF_EARLY_CALENDAR_DAYS,
    REFERRAL_SLA_SNF_ROUTINE_CALENDAR_DAYS,
    REFERRAL_SLA_SNF_URGENT_HOURS,
    SCHOOL_URGENT_LESION_THRESHOLD,
    SEALANT_ELIGIBLE_SURFACES,
    SEALANT_ELIGIBLE_TOOTH_NUMBERS,
    SLIDING_FEE_BAND_A_MAX_FPL_PCT,
    SLIDING_FEE_BAND_B_MAX_FPL_PCT,
    SLIDING_FEE_BAND_C_MAX_FPL_PCT,
    SLIDING_FEE_BAND_D_MAX_FPL_PCT,
    SLIDING_FEE_DISCOUNT,
    SLIDING_FEE_NOMINAL_FEE_CENTS,
    SNF_MEDICAL_COMPLEXITY_THRESHOLD,
    SNF_ORAL_HYGIENE_POOR_THRESHOLD,
    SPORE_TAINT_LOOKBACK_DAYS,
    SUPERVISION_MATRIX,
    SUPERVISION_RANK,
    SUPPLY_SURCHARGE_TIER1_CENTS,
    SUPPLY_SURCHARGE_TIER1_MAX_SUBTOTAL_CENTS,
    SUPPLY_SURCHARGE_TIER2_CENTS,
    SUPPLY_SURCHARGE_TIER2_MAX_SUBTOTAL_CENTS,
    SUPPLY_SURCHARGE_TIER3_CENTS,
    UNIT_CALIBRATION_DUE_WARNING_DAYS,
    UNIT_CALIBRATION_VALID_DAYS,
    UNIT_TRANSPORT_BUFFER_MINUTES,
)
from timefmt import (
    add_business_days,
    add_days,
    add_hours,
    end_of_day_instant,
    instant_date,
    timedelta,
)


def round_half_up_cents(value):
    """Round a Decimal amount half up to a whole cent."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------
# consent_expires_at
# --------------------------------------------------------------------------
def consent_expiry(regime, signed_at, program_period):
    if regime == "SCHOOL_GUARDIAN":
        return end_of_day_instant(program_period["ends_on"]), None
    expires = add_days(signed_at, CONSENT_SNF_REAFFIRMATION_DAYS)
    return expires, expires


# --------------------------------------------------------------------------
# triage_band
# --------------------------------------------------------------------------
def triage_band(site_type, findings):
    lesions = findings.get("cavitated_lesion_count")
    lesions = lesions if isinstance(lesions, int) else 0
    pain = bool(findings.get("pain_reported"))
    abscess = bool(findings.get("abscess_or_swelling"))
    decay = bool(findings.get("untreated_decay_present"))
    denture = bool(findings.get("denture_problem"))
    hygiene = findings.get("oral_hygiene_score")
    hygiene = hygiene if isinstance(hygiene, int) else None
    complexity = findings.get("medical_complexity_count")
    complexity = complexity if isinstance(complexity, int) else None

    if site_type == "SCHOOL":
        if abscess:
            return "URGENT"
        if pain and lesions >= SCHOOL_URGENT_LESION_THRESHOLD:
            return "URGENT"
        if lesions >= 1 or decay:
            return "EARLY_CARE_NEEDED"
        return "NO_OBVIOUS_PROBLEM"

    if abscess or pain:
        return "URGENT"
    if lesions >= 1 and complexity is not None and complexity >= SNF_MEDICAL_COMPLEXITY_THRESHOLD:
        return "URGENT"
    if lesions >= 1 or denture or (hygiene is not None and hygiene >= SNF_ORAL_HYGIENE_POOR_THRESHOLD):
        return "EARLY_CARE_NEEDED"
    return "NO_OBVIOUS_PROBLEM"


# --------------------------------------------------------------------------
# unit_calibration_status
# --------------------------------------------------------------------------
def calibration_projection(unit):
    """Read-derived: (calibration_due_on, calibration_status)."""
    last = unit.get("last_calibrated_on")
    if last is None:
        return None, "EXPIRED"
    due = add_days(last, UNIT_CALIBRATION_VALID_DAYS)
    today = clock.today()
    if today > due:
        return due, "EXPIRED"
    if today >= add_days(due, -UNIT_CALIBRATION_DUE_WARNING_DAYS):
        return due, "DUE"
    return due, "CURRENT"


# --------------------------------------------------------------------------
# site_visit_capacity_chair_minutes
# --------------------------------------------------------------------------
def capacity_chair_minutes(chair_count, start, end):
    duration_minutes = int((end - start).total_seconds()) // 60
    return (chair_count * duration_minutes * CHAIR_UTILIZATION_CAP_PCT_NUM) // CHAIR_UTILIZATION_CAP_PCT_DEN


# --------------------------------------------------------------------------
# site_visit_booked_chair_minutes -- full recomputation, never patched
# --------------------------------------------------------------------------
def visit_encounters(site_visit_id):
    return [e for e in store.all_rows("encounters") if e["site_visit_id"] == site_visit_id]


def encounter_procedures(encounter_id):
    return [p for p in store.all_rows("procedures") if p["encounter_id"] == encounter_id]


def booked_chair_minutes(site_visit_id):
    encounter_ids = {e["id"] for e in visit_encounters(site_visit_id)}
    total = 0
    for proc in store.all_rows("procedures"):
        if proc["encounter_id"] in encounter_ids and proc["status"] in ("PLANNED", "PERFORMED"):
            total += proc["chair_minutes"]
    return total


# --------------------------------------------------------------------------
# varnish ledgers -- full recomputation over surviving rows
# --------------------------------------------------------------------------
def varnish_stats(patient_id, program_period_id):
    """(count, last_date) of PERFORMED D1206 rows for a patient inside a period."""
    count = 0
    last_date = None
    for proc in store.all_rows("procedures"):
        if proc["procedure_code"] != "D1206" or proc["status"] != "PERFORMED":
            continue
        encounter = store.get("encounters", proc["encounter_id"])
        if encounter is None or encounter["patient_id"] != patient_id:
            continue
        visit = store.get("site_visits", encounter["site_visit_id"])
        if visit is None or visit["program_period_id"] != program_period_id:
            continue
        count += 1
        if proc.get("performed_at") is not None:
            candidate = instant_date(proc["performed_at"])
            if last_date is None or candidate > last_date:
                last_date = candidate
    return count, last_date


def recompute_varnish(patient_id, program_period_id):
    patient = store.get("patients", patient_id)
    if patient is None:
        return
    count, last_date = varnish_stats(patient_id, program_period_id)
    patient["varnish_applications_in_period"] = count
    patient["last_varnish_date"] = last_date


# --------------------------------------------------------------------------
# sliding_fee_band
# --------------------------------------------------------------------------
def sliding_fee(household_size, annual_income_cents):
    threshold = FPL_BASE_ANNUAL_CENTS + FPL_PER_ADDITIONAL_PERSON_CENTS * (household_size - 1)
    percent = (Decimal(annual_income_cents) / Decimal(threshold) * Decimal(100)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    if percent <= Decimal(SLIDING_FEE_BAND_A_MAX_FPL_PCT):
        band = "A"
    elif percent <= Decimal(SLIDING_FEE_BAND_B_MAX_FPL_PCT):
        band = "B"
    elif percent <= Decimal(SLIDING_FEE_BAND_C_MAX_FPL_PCT):
        band = "C"
    elif percent <= Decimal(SLIDING_FEE_BAND_D_MAX_FPL_PCT):
        band = "D"
    else:
        band = "E"
    return percent, band


# --------------------------------------------------------------------------
# encounter pricing
# --------------------------------------------------------------------------
def performed_procedures(encounter_id):
    return [p for p in encounter_procedures(encounter_id) if p["status"] == "PERFORMED"]


def encounter_subtotal_cents(encounter_id):
    return sum(p["charge_cents"] for p in performed_procedures(encounter_id))


def supply_surcharge_cents(subtotal_cents):
    if subtotal_cents == 0:
        return 0
    if subtotal_cents <= SUPPLY_SURCHARGE_TIER1_MAX_SUBTOTAL_CENTS:
        return SUPPLY_SURCHARGE_TIER1_CENTS
    if subtotal_cents <= SUPPLY_SURCHARGE_TIER2_MAX_SUBTOTAL_CENTS:
        return SUPPLY_SURCHARGE_TIER2_CENTS
    return SUPPLY_SURCHARGE_TIER3_CENTS


def charge_projection(encounter_id):
    """(subtotal, surcharge, total) over the encounter's surviving PERFORMED rows."""
    subtotal = encounter_subtotal_cents(encounter_id)
    surcharge = supply_surcharge_cents(subtotal)
    return subtotal, surcharge, subtotal + surcharge


PRICING_REGIME_BY_PAYER = {
    "MEDICAID_MCO": "MEDICAID_ENCOUNTER_RATE",
    "COMMERCIAL_FFS": "COMMERCIAL_FEE_SCHEDULE",
    "UNINSURED": "UNINSURED_SLIDING_FEE",
}


def price_encounter(encounter, coverage, manual_patient_responsibility_cents=None):
    """Run the six-step pricing pass in its pinned order."""
    performed = performed_procedures(encounter["id"])

    # Step one -- the subtotal.
    subtotal = sum(p["charge_cents"] for p in performed)
    # Step two -- the supply surcharge, keyed on the PRE-surcharge figure.
    surcharge = supply_surcharge_cents(subtotal)
    total = subtotal + surcharge
    # Step three -- the regime fork.
    regime = PRICING_REGIME_BY_PAYER[coverage["payer_type"]]

    # Step four -- the allowed amount under Medicaid and commercial.
    if regime == "MEDICAID_ENCOUNTER_RATE":
        allowed = 0 if not performed else min(MEDICAID_ENCOUNTER_RATE_CENTS, total)
    elif regime == "COMMERCIAL_FEE_SCHEDULE":
        allowed = sum(
            min(p["charge_cents"], COMMERCIAL_ALLOWED_SCHEDULE_CENTS[p["procedure_code"]])
            for p in performed
        )
    else:
        allowed = 0  # assigned in step six, after the patient's share exists

    # Step five -- the patient's share.
    if not performed:
        responsibility = 0
    elif regime == "MEDICAID_ENCOUNTER_RATE":
        responsibility = 0
    elif regime == "COMMERCIAL_FEE_SCHEDULE":
        responsibility = round_half_up_cents(Decimal(allowed) * Decimal(COMMERCIAL_COINSURANCE_PCT))
    else:
        band = coverage.get("sliding_fee_band")
        discount = Decimal(SLIDING_FEE_DISCOUNT[band])
        factor = Decimal("1") - discount
        per_line = [round_half_up_cents(Decimal(p["charge_cents"]) * factor) for p in performed]
        discounted_total = sum(per_line)
        if band == "E":
            responsibility = discounted_total
        else:
            responsibility = max(discounted_total, SLIDING_FEE_NOMINAL_FEE_CENTS)

    # The manual override replaces the computed share; the allowed amount
    # follows the regime.
    if manual_patient_responsibility_cents is not None:
        responsibility = manual_patient_responsibility_cents
        if regime == "UNINSURED_SLIDING_FEE":
            allowed = manual_patient_responsibility_cents
    elif regime == "UNINSURED_SLIDING_FEE":
        # Step six -- self-pay: the allowed amount IS the patient's share.
        allowed = responsibility

    plan_paid = allowed - responsibility
    write_off = total - allowed

    return {
        "subtotal_cents": subtotal,
        "supply_surcharge_cents": surcharge,
        "total_charge_cents": total,
        "allowed_amount_cents": allowed,
        "patient_responsibility_cents": responsibility,
        "plan_paid_cents": plan_paid,
        "write_off_cents": write_off,
        "pricing_regime": regime,
    }


# --------------------------------------------------------------------------
# referral_due_at
# --------------------------------------------------------------------------
def referral_due_at(base_instant, urgency_band, site_type):
    if site_type == "SCHOOL":
        if urgency_band == "URGENT":
            n = REFERRAL_SLA_SCHOOL_URGENT_BUSINESS_DAYS
        elif urgency_band == "EARLY_CARE_NEEDED":
            n = REFERRAL_SLA_SCHOOL_EARLY_BUSINESS_DAYS
        else:
            n = REFERRAL_SLA_SCHOOL_ROUTINE_BUSINESS_DAYS
        return add_business_days(base_instant, n)
    if urgency_band == "URGENT":
        return add_hours(base_instant, REFERRAL_SLA_SNF_URGENT_HOURS)
    if urgency_band == "EARLY_CARE_NEEDED":
        return add_days(base_instant, REFERRAL_SLA_SNF_EARLY_CALENDAR_DAYS)
    return add_days(base_instant, REFERRAL_SLA_SNF_ROUTINE_CALENDAR_DAYS)


# --------------------------------------------------------------------------
# follow_up_due_date and follow_up_status
# --------------------------------------------------------------------------
def follow_up_days(urgency_band):
    if urgency_band == "URGENT":
        return FOLLOW_UP_URGENT_DAYS
    if urgency_band == "EARLY_CARE_NEEDED":
        return FOLLOW_UP_EARLY_DAYS
    return FOLLOW_UP_ROUTINE_DAYS


def follow_up_due_date(plan):
    if plan.get("last_contact_at") is not None:
        anchor = instant_date(plan["last_contact_at"])
    else:
        anchor = plan.get("activated_on")
    if anchor is None:
        return None
    return anchor + timedelta(days=follow_up_days(plan.get("urgency_band")))


def follow_up_status(plan):
    due = plan.get("follow_up_due_date")
    if due is None:
        return "NOT_DUE"
    today = clock.today()
    if plan.get("last_contact_at") is not None and today < due:
        return "CONTACTED"
    if today < due:
        return "NOT_DUE"
    if today <= due + timedelta(days=FOLLOW_UP_GRACE_DAYS):
        return "DUE"
    return "OVERDUE"


# --------------------------------------------------------------------------
# sealant_surface_eligibility
# --------------------------------------------------------------------------
def sealant_eligible(patient_id, tooth_number, surface, exclude_procedure_id=None):
    if tooth_number is None or surface is None:
        return False
    if tooth_number not in SEALANT_ELIGIBLE_TOOTH_NUMBERS:
        return False
    if surface not in SEALANT_ELIGIBLE_SURFACES:
        return False
    for proc in store.all_rows("procedures"):
        if proc["procedure_code"] != "D1351":
            continue
        if proc["id"] == exclude_procedure_id:
            continue
        if proc["status"] not in ("PLANNED", "PERFORMED"):
            continue
        if proc.get("tooth_number") != tooth_number or proc.get("surface") != surface:
            continue
        encounter = store.get("encounters", proc["encounter_id"])
        if encounter is not None and encounter["patient_id"] == patient_id:
            return False
    return True


# --------------------------------------------------------------------------
# supervision_permitted
# --------------------------------------------------------------------------
def supervision_permitted(procedure_code, staff, site_visit):
    required = SUPERVISION_MATRIX[procedure_code].get(staff["staff_role"], "NOT_PERMITTED")
    if required == "NOT_PERMITTED":
        return False
    if SUPERVISION_RANK[staff["supervision_level"]] < SUPERVISION_RANK[required]:
        return False
    if required in ("DIRECT", "INDIRECT"):
        candidates = [site_visit.get("onsite_dentist_staff_id")]
    elif required == "GENERAL":
        candidates = [
            site_visit.get("onsite_dentist_staff_id"),
            site_visit.get("remote_dentist_staff_id"),
        ]
    else:
        return True
    for candidate in candidates:
        if candidate is None:
            continue
        dentist = store.get("staff_members", candidate)
        if dentist is None:
            continue
        if dentist["credential_status"] == "ACTIVE" and dentist["staff_role"] == "DENTIST":
            return True
    return False


# --------------------------------------------------------------------------
# resource_overlap_detection
# --------------------------------------------------------------------------
LIVE_VISIT_STATUSES = ("SCHEDULED", "HOLD_BLOCKED", "IN_PROGRESS")


def unit_collision(portable_unit_id, start, end, exclude_visit_id=None):
    buffer_delta = timedelta(minutes=UNIT_TRANSPORT_BUFFER_MINUTES)
    for visit in store.all_rows("site_visits"):
        if visit["id"] == exclude_visit_id:
            continue
        if visit["status"] not in LIVE_VISIT_STATUSES:
            continue
        if visit["portable_unit_id"] != portable_unit_id:
            continue
        if start < visit["scheduled_end_at"] + buffer_delta and visit["scheduled_start_at"] < end + buffer_delta:
            return True
    return False


def staff_collision(staff_ids, start, end, exclude_visit_id=None):
    wanted = {s for s in staff_ids if s}
    if not wanted:
        return False
    for visit in store.all_rows("site_visits"):
        if visit["id"] == exclude_visit_id:
            continue
        if visit["status"] not in LIVE_VISIT_STATUSES:
            continue
        other = {
            visit.get("lead_staff_id"),
            visit.get("onsite_dentist_staff_id"),
            visit.get("remote_dentist_staff_id"),
        }
        other = {s for s in other if s}
        if not (other & wanted):
            continue
        if start <= visit["scheduled_end_at"] and visit["scheduled_start_at"] <= end:
            return True
    return False


# --------------------------------------------------------------------------
# spore_taint_set
# --------------------------------------------------------------------------
def spore_taint_loads(failed_load, unit):
    cutoff_by_window = add_days(failed_load["cycle_completed_at"], -SPORE_TAINT_LOOKBACK_DAYS)
    cutoff_by_pass = unit.get("last_passed_load_at")
    if cutoff_by_pass is not None:
        cutoff = max(cutoff_by_pass, cutoff_by_window)
    else:
        cutoff = cutoff_by_window
    loads = []
    for load in store.all_rows("sterilization_loads"):
        if load["portable_unit_id"] != unit["id"]:
            continue
        if load["spore_result"] == "PASSED":
            continue
        if not (load["cycle_completed_at"] > cutoff):
            continue
        if not (load["cycle_completed_at"] <= failed_load["cycle_completed_at"]):
            continue
        loads.append(load)
    loads.sort(key=lambda l: (l["cycle_completed_at"], l["_seq"]))
    return loads


def latest_load_for_unit(portable_unit_id):
    """Most recent load by cycle_completed_at DESC, insertion order as tie-break."""
    loads = [l for l in store.all_rows("sterilization_loads") if l["portable_unit_id"] == portable_unit_id]
    if not loads:
        return None
    loads.sort(key=lambda l: (l["cycle_completed_at"], l["_seq"]))
    return loads[-1]


__all__ = [name for name in dir() if not name.startswith("_")]
