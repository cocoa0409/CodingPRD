"""Deterministic calculations (PRD sections 2.6 - 2.8 and the calculation rules)."""
from decimal import Decimal, ROUND_HALF_UP

import db
from db import store

SCREENING_BENCHMARK_DAYS = 30
DIAGNOSTIC_BENCHMARK_DAYS = 90
EI_BENCHMARK_DAYS = 180
LATE_GRACE_DAYS = 45

FULL_TERM_WEEKS = 40
CORRECTED_GA_THRESHOLD = 35
CORRECTED_NICU_THRESHOLD = 5

SETTING_POINTS = {
    "INPATIENT": 0,
    "BIRTHING_CENTER": 8,
    "OUT_OF_HOSPITAL": 12,
    "HOME_BIRTH": 15,
}

OPEN_EPISODE_STATUSES = ("PENDING_SCHEDULING", "SCHEDULED", "ESCALATED_DIAGNOSTIC")
RESOLVED_EPISODE_STATUSES = ("RESOLVED_PASS", "RESOLVED_DIAGNOSED", "RESOLVED_NO_LOSS")
OPEN_RISK_STATUSES = ("ACTIVE", "SURVEILLANCE_DUE", "SURVEILLANCE_OVERDUE")
BUDGET_HOLDING_TASK_STATUSES = ("UNASSIGNED", "OPEN", "COMPLETED")
SLOT_HOLDING_APPOINTMENT_STATUSES = ("BOOKED", "ATTENDED")
ATTEMPT_APPOINTMENT_STATUSES = ("BOOKED", "ATTENDED", "NO_SHOW")
ASSESSABLE_FACILITY_TYPES = ("BIRTH_HOSPITAL", "BIRTHING_CENTER", "MIDWIFE_PRACTICE",
                             "AUDIOLOGY_CLINIC")
SHORT_SURVEILLANCE_CODES = ("CMV", "BACTERIAL_MENINGITIS", "ECMO")

WEIGHT_SCREEN = Decimal("0.50")
WEIGHT_RESOLUTION = Decimal("0.30")
WEIGHT_REPORTING = Decimal("0.20")

ATTEMPT_CEILING = 3
FAMILY_BURDEN_SECONDS = 86400
TRAVEL_BUFFER_SECONDS = 45 * 60


# --- age and timeliness -----------------------------------------------------
def age_parts(infant, reference):
    chronological = db.floor_days(reference, infant["birth_datetime"])
    offset = max(0, (FULL_TERM_WEEKS - infant["gestational_age_weeks"]) * 7)
    corrected = max(0, chronological - offset)
    if (infant["gestational_age_weeks"] < CORRECTED_GA_THRESHOLD
            or infant["nicu_stay_days"] >= CORRECTED_NICU_THRESHOLD):
        basis = "CORRECTED"
        effective = corrected
    else:
        basis = "CHRONOLOGICAL"
        effective = chronological
    return {
        "chronological_age_days": chronological,
        "prematurity_offset_days": offset,
        "corrected_age_days": corrected,
        "benchmark_age_basis": basis,
        "effective_age_days": effective,
    }


def effective_age(infant, reference):
    return age_parts(infant, reference)["effective_age_days"]


def chronological_age(infant, reference):
    return age_parts(infant, reference)["chronological_age_days"]


def timeliness(age_days, benchmark_days, complete):
    if complete:
        return "ON_TIME" if age_days <= benchmark_days else "LATE"
    return "PENDING" if age_days <= benchmark_days else "OVERDUE"


def overall_result(left, right):
    if left == "PASS" and right == "PASS":
        return "PASS"
    if left == "NOT_TESTED" and right == "NOT_TESTED":
        return "INCOMPLETE"
    return "REFER"


def surveillance_due_date(infant, code):
    days = 180 if code in SHORT_SURVEILLANCE_CODES else 270
    return db.add_days(infant["birth_datetime"], days)


# --- derived collection queries ---------------------------------------------
def infant_episodes(infant_id):
    return [e for e in store.episodes.values() if e["infant_id"] == infant_id]


def open_episodes(infant_id):
    return [e for e in infant_episodes(infant_id)
            if e["status"] in OPEN_EPISODE_STATUSES]


def active_episode(infant_id):
    """The open episode with the most recent created_at (ids never consulted)."""
    return db.latest(open_episodes(infant_id))


def episode_appointments(episode_id):
    return [a for a in store.appointments.values() if a["episode_id"] == episode_id]


def attempt_count(episode):
    return len([a for a in episode_appointments(episode["id"])
                if a["status"] in ATTEMPT_APPOINTMENT_STATUSES])


def slot_booked_count(slot):
    return len([a for a in store.appointments.values()
                if a["slot_id"] == slot["id"]
                and a["status"] in SLOT_HOLDING_APPOINTMENT_STATUSES])


def slot_remaining(slot):
    return slot["total_capacity"] - slot_booked_count(slot)


def slot_status(slot):
    return "OPEN" if slot_remaining(slot) > 0 else "FULL"


def infant_appointments(infant_id):
    return [a for a in store.appointments.values() if a["infant_id"] == infant_id]


def missed_appointment_count(infant_id):
    return len([a for a in infant_appointments(infant_id) if a["status"] == "NO_SHOW"])


def infant_risk_entries(infant_id):
    return [r for r in store.risk_entries.values() if r["infant_id"] == infant_id]


def open_risk_entries(infant_id):
    return [r for r in infant_risk_entries(infant_id)
            if r["status"] in OPEN_RISK_STATUSES]


def risk_factor_count(infant_id):
    return len(open_risk_entries(infant_id))


def infant_tasks(infant_id):
    return [t for t in store.tasks.values() if t["infant_id"] == infant_id]


def provider_open_task_count(provider_id):
    return len([t for t in store.tasks.values()
                if t["assigned_provider_id"] == provider_id and t["status"] == "OPEN"])


def facility_tasks(facility_id):
    return [t for t in store.tasks.values() if t["funding_facility_id"] == facility_id]


def facility_units_reserved(facility_id):
    return sum(t["units_reserved"] for t in facility_tasks(facility_id)
               if t["status"] in BUDGET_HOLDING_TASK_STATUSES)


def budget_remaining(facility):
    return facility["navigation_budget_units_total"] - facility_units_reserved(
        facility["id"])


def facility_reports(facility_id):
    return [r for r in store.reports.values() if r["facility_id"] == facility_id]


def penalty_balance(facility):
    total = facility["manual_adjustment_points_total"]
    for report in facility_reports(facility["id"]):
        if report["status"] == "ACCEPTED":
            total += report["assessed_penalty_points"]
    return total


def compliance_posture(balance):
    if balance <= 4:
        return "COMPLIANT"
    if balance <= 9:
        return "WATCH"
    if balance <= 17:
        return "PROBATION"
    return "SUSPENDED"


def facility_posture(facility):
    return compliance_posture(penalty_balance(facility))


def facility_infants(facility_id):
    return [i for i in store.infants.values() if i["birth_facility_id"] == facility_id]


def report_of_record(facility_id, period_id):
    candidates = [r for r in store.reports.values()
                  if r["facility_id"] == facility_id
                  and r["reporting_period_id"] == period_id
                  and r["status"] != "SUPERSEDED"]
    return db.latest(candidates)


# --- navigation cost --------------------------------------------------------
def navigation_units_required(infant, task_type):
    units = 2
    if infant["interpreter_required"]:
        units += 3
    if task_type == "HOME_VISIT":
        units += 4
    return units


# --- loss-to-follow-up risk -------------------------------------------------
def ltf_risk(infant):
    score = SETTING_POINTS[infant["birth_setting"]]
    if infant["interpreter_required"]:
        facility = store.facilities.get(infant["birth_facility_id"])
        region = facility["region_code"] if facility else None
        matches = [p for p in store.providers.values()
                   if p["provider_type"] == "NAVIGATOR"
                   and p["credential_status"] == "ACTIVE"
                   and p["region_code"] == region
                   and infant["preferred_language"] in p["languages"]]
        if not matches:
            score += 10
    score += min(24, 6 * missed_appointment_count(infant["id"]))
    score += min(16, 4 * risk_factor_count(infant["id"]))
    episode = active_episode(infant["id"])
    if episode is not None:
        benchmark = episode["benchmark_days"]
        age = effective_age(infant, db.now())
        if age <= benchmark - 10:
            pressure = 0
        elif age <= benchmark:
            pressure = 12
        else:
            pressure = 20
        score += pressure
        if episode["escalation_flag"]:
            score += 6
    outreach = [t for t in infant_tasks(infant["id"])
                if t["status"] in BUDGET_HOLDING_TASK_STATUSES]
    if outreach:
        score -= 8
    score = max(0, min(100, score))
    if score >= 45:
        band = "CRITICAL"
    elif score >= 30:
        band = "HIGH"
    elif score >= 15:
        band = "ELEVATED"
    else:
        band = "LOW"
    return score, band


# --- selectors --------------------------------------------------------------
def navigator_candidates(infant, excluded=()):
    facility = store.facilities.get(infant["birth_facility_id"])
    region = facility["region_code"] if facility else None
    pool = []
    for provider in store.providers.values():
        if provider["provider_type"] != "NAVIGATOR":
            continue
        if provider["credential_status"] != "ACTIVE":
            continue
        if provider["region_code"] != region:
            continue
        if provider_open_task_count(provider["id"]) >= provider["max_open_tasks"]:
            continue
        if infant["interpreter_required"] and (
                infant["preferred_language"] not in provider["languages"]):
            continue
        if provider["id"] in excluded:
            continue
        pool.append(provider)
    pool.sort(key=lambda p: (provider_open_task_count(p["id"]),
                             -p["max_open_tasks"],
                             p["created_at"],
                             p["_seq"]))
    return pool


def pending_referral_load(facility_id):
    return len([r for r in store.referrals.values()
                if r["ei_program_facility_id"] == facility_id
                and r["status"] in ("PENDING", "ACCEPTED")])


def ei_program_candidates(infant, excluded=()):
    facility = store.facilities.get(infant["birth_facility_id"])
    region = facility["region_code"] if facility else None
    tier_one = []
    tier_two = []
    for candidate in store.facilities.values():
        if candidate["facility_type"] != "EI_PROGRAM":
            continue
        if facility_posture(candidate) not in ("COMPLIANT", "WATCH"):
            continue
        if candidate["id"] in excluded:
            continue
        tier_two.append(candidate)
        if candidate["region_code"] == region:
            tier_one.append(candidate)
    pool = tier_one if tier_one else tier_two
    pool.sort(key=lambda f: (pending_referral_load(f["id"]),
                             f["created_at"],
                             f["_seq"]))
    return pool


# --- precision helpers ------------------------------------------------------
def round4(value):
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def round2(value):
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_int(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _ratio(numerator, denominator):
    if denominator == 0:
        return None
    return round4(Decimal(numerator) / Decimal(denominator))


# --- facility performance score --------------------------------------------
def facility_performance(facility, period):
    start = period["period_start"]
    end = period["period_end"]
    facility_id = facility["id"]

    cohort = [i for i in facility_infants(facility_id)
              if start <= i["birth_datetime"] < end]
    cohort_denominator = len(cohort)
    cohort_numerator = 0
    for infant in cohort:
        screened = [e for e in store.encounters.values()
                    if e["infant_id"] == infant["id"]
                    and e["facility_id"] == facility_id
                    and e["encounter_type"] == "BIRTH_ADMISSION"
                    and e["before_discharge"]]
        if screened:
            cohort_numerator += 1

    window_encounters = [e for e in store.encounters.values()
                         if e["facility_id"] == facility_id
                         and e["encounter_type"] == "BIRTH_ADMISSION"
                         and start <= e["performed_at"] < end]
    encounter_denominator = len(set(e["infant_id"] for e in window_encounters))
    encounter_numerator = len(set(e["infant_id"] for e in window_encounters
                                  if e["before_discharge"]))

    infant_ids = set(i["id"] for i in facility_infants(facility_id))
    window_episodes = [e for e in store.episodes.values()
                       if e["infant_id"] in infant_ids
                       and start <= e["created_at"] < end]
    r2_denominator = len(window_episodes)
    r2_numerator = len([e for e in window_episodes
                        if e["status"] in RESOLVED_EPISODE_STATUSES])

    record = report_of_record(facility_id, period["id"])
    if record is not None and not record["submitted_late"] and not record["auto_generated"]:
        r3 = Decimal("1.0000")
    else:
        r3 = Decimal("0.0000")

    r1_cohort = _ratio(cohort_numerator, cohort_denominator)
    r1_encounter = _ratio(encounter_numerator, encounter_denominator)
    r2 = _ratio(r2_numerator, r2_denominator)

    score = None
    encounter_score = None
    if r2 is not None:
        if r1_cohort is not None:
            total = (r1_cohort * WEIGHT_SCREEN + r2 * WEIGHT_RESOLUTION
                     + r3 * WEIGHT_REPORTING)
            score = round2(total * Decimal(100))
        if r1_encounter is not None:
            total = (r1_encounter * WEIGHT_SCREEN + r2 * WEIGHT_RESOLUTION
                     + r3 * WEIGHT_REPORTING)
            encounter_score = round2(total * Decimal(100))
    return {
        "performance_score": score,
        "encounter_basis_performance_score": encounter_score,
        "cohort_screened_rate": r1_cohort,
        "encounter_screened_rate": r1_encounter,
        "followup_resolution_rate": r2,
        "report_timeliness_rate": round4(r3),
    }


# --- penalty assessment -----------------------------------------------------
def penalty_assessment(facility, report):
    if report["auto_generated"]:
        variance = report["actual_refer_count"] or 0
        base = 2 * variance + 5
    else:
        variance = report["variance_case_count"] or 0
        base = 2 * variance + (3 if report["submitted_late"] else 0)
    carryover = penalty_balance(facility)
    tier_input = base + carryover
    if tier_input <= 4:
        surcharge = Decimal("0.00")
    elif tier_input <= 9:
        surcharge = Decimal("0.25")
    else:
        surcharge = Decimal("0.50")
    assessed = round_int(Decimal(base) * (Decimal(1) + surcharge))
    return {
        "base_points": base,
        "carryover": carryover,
        "tier_input": tier_input,
        "surcharge_pct": surcharge,
        "assessed_penalty_points": assessed,
        "balance": carryover + assessed,
    }


def report_actual_counts(facility_id, period):
    """Distinct infants with a BIRTH_ADMISSION encounter in the window, and the
    count of the facility's encounters in the window whose overall_result is REFER."""
    start = period["period_start"]
    end = period["period_end"]
    encounters = [e for e in store.encounters.values()
                  if e["facility_id"] == facility_id
                  and start <= e["performed_at"] < end]
    screened = len(set(e["infant_id"] for e in encounters
                       if e["encounter_type"] == "BIRTH_ADMISSION"))
    refer = len([e for e in encounters if e["overall_result"] == "REFER"])
    return screened, refer


def period_label(period):
    return "%s..%s" % (db.fmt_dt(period["period_start"]),
                       db.fmt_dt(period["period_end"]))
