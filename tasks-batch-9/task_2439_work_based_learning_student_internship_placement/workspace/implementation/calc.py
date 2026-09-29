"""Calculations (PRD 2.7 and section 3): every compliance fact is computed."""

from decimal import Decimal, ROUND_HALF_UP

from db import by_created, db, to_date

ZERO = Decimal("0")
CENT = Decimal("1")
TWO = Decimal("0.01")
FOUR = Decimal("0.0001")


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rh(value, places=0):
    """Half-up rounding to `places` decimals."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rh_int(value):
    return int(rh(value, 0))


# --------------------------------------------------------------------------
# student eligibility (PRD 3.4)
# --------------------------------------------------------------------------

MIN_GRADE_LEVEL = 10
MIN_GPA = Decimal("2.00")
MIN_ATTENDANCE = Decimal("0.90")


def student_eligibility_status(grade_level, gpa, attendance_rate):
    if grade_level < MIN_GRADE_LEVEL:
        return "INELIGIBLE_GRADE"
    if dec(gpa) < MIN_GPA:
        return "INELIGIBLE_ACADEMIC"
    if dec(attendance_rate) < MIN_ATTENDANCE:
        return "INELIGIBLE_ATTENDANCE"
    return "ELIGIBLE"


# --------------------------------------------------------------------------
# employer safety score and posture (PRD 3.2)
# --------------------------------------------------------------------------

MINOR_PENALTY = 15
MODERATE_PENALTY = 30
CRITICAL_PENALTY = 50
CONDITIONAL_SITE_PENALTY = 10
SCORE_FLOOR = 0
SCORE_CEILING = 100
SUSPEND_THRESHOLD = 50
PROBATION_THRESHOLD = 70

SCORING_INCIDENT_STATUSES = ("SUBSTANTIATED", "CLOSED")


def partner_worksites(partner_id):
    return [w for w in db.worksites.values() if w["employer_partner_id"] == partner_id]


def partner_incident_counts(partner_id):
    site_ids = {w["id"] for w in partner_worksites(partner_id)}
    counts = {"MINOR": 0, "MODERATE": 0, "CRITICAL": 0}
    for inc in db.incident_reports.values():
        if inc["worksite_id"] in site_ids and inc["status"] in SCORING_INCIDENT_STATUSES:
            if inc["severity"] in counts:
                counts[inc["severity"]] += 1
    return counts


def employer_safety_score_posture(partner_id):
    counts = partner_incident_counts(partner_id)
    sites = partner_worksites(partner_id)
    conditional_sites = sum(1 for w in sites if w["safety_status"] == "CONDITIONAL")
    raw = (100
           - MINOR_PENALTY * counts["MINOR"]
           - MODERATE_PENALTY * counts["MODERATE"]
           - CRITICAL_PENALTY * counts["CRITICAL"]
           - CONDITIONAL_SITE_PENALTY * conditional_sites)
    score = min(SCORE_CEILING, max(SCORE_FLOOR, raw))

    if any(w["safety_status"] == "FAILED" for w in sites) or score < SUSPEND_THRESHOLD:
        posture = "SUSPENDED"
    elif score < PROBATION_THRESHOLD:
        posture = "PROBATION"
    elif any(w["safety_status"] in ("APPROVED", "CONDITIONAL") for w in sites):
        posture = "ELIGIBLE"
    else:
        posture = "PROSPECT"
    return counts, score, posture


# --------------------------------------------------------------------------
# child labor hour ledger (PRD 3.7)
# --------------------------------------------------------------------------

BANDS = {
    "MINOR_14_15": {
        "daily_school": Decimal("3.00"),
        "daily_non_school": Decimal("8.00"),
        "weekly_school": Decimal("18.00"),
        "weekly_non_school": Decimal("40.00"),
        "earliest": "07:00",
        "night_cutoff": "19:00",
    },
    "MINOR_16_17": {
        "daily_school": Decimal("4.00"),
        "daily_non_school": Decimal("8.00"),
        "weekly_school": Decimal("28.00"),
        "weekly_non_school": Decimal("48.00"),
        "earliest": "06:00",
        "night_cutoff": "22:00",
    },
}


def minutes_of(hhmm):
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def shift_hours(start_time, end_time, break_minutes):
    raw = Decimal(minutes_of(end_time) - minutes_of(start_time) - break_minutes) / Decimal(60)
    return rh(raw, 2)


def week_start(work_date):
    """Sunday-start week containing work_date."""
    d = to_date(work_date)
    from datetime import timedelta
    return (d - timedelta(days=(d.weekday() + 1) % 7))


def week_span(work_date):
    from datetime import timedelta
    start = week_start(work_date)
    return start.isoformat(), (start + timedelta(days=6)).isoformat()


# --------------------------------------------------------------------------
# wage settlement (PRD 3.10)
# --------------------------------------------------------------------------

MIN_WAGE_CENTS = 1500
LEARNER_WAGE_FLOOR_CENTS = 1275


def logged_entries(placement_id):
    return by_created([e for e in db.timesheet_entries.values()
                       if e["placement_id"] == placement_id and e["status"] == "LOGGED"])


def total_logged_hours(placement_id):
    entries = logged_entries(placement_id)
    return rh(sum((dec(e["hours_worked"]) for e in entries), ZERO), 2)


def wage_variants(placement):
    """Returns (provisional_wage_cents, final_wage_cents)."""
    pay = placement["pay_classification"]
    if pay == "STIPEND":
        stipend = int(placement["stipend_total_cents"])
        return stipend, stipend
    rate = int(placement["hourly_wage_cents"]) if pay == "PAID" else 0
    entries = logged_entries(placement["id"])
    provisional = 0
    for entry in entries:
        provisional += rh_int(dec(entry["hours_worked"]) * Decimal(rate))
    total_hours = rh(sum((dec(e["hours_worked"]) for e in entries), ZERO), 2)
    final = rh_int(total_hours * Decimal(rate))
    return provisional, final


# --------------------------------------------------------------------------
# academic credit (PRD 3.10)
# --------------------------------------------------------------------------

HOURS_PER_HALF_CREDIT = Decimal("45")
MAX_RATING = Decimal("5.00")

RATING_WEIGHTS = (
    ("rating_technical", Decimal("0.30")),
    ("rating_communication", Decimal("0.20")),
    ("rating_reliability", Decimal("0.20")),
    ("rating_safety", Decimal("0.20")),
    ("rating_initiative", Decimal("0.10")),
)


def competency_score(ratings):
    total = ZERO
    for name, weight in RATING_WEIGHTS:
        total += weight * Decimal(int(ratings[name]))
    return rh(total, 2)


def closed_cycles(placement_id):
    cycles = [c for c in db.evaluation_cycles.values()
              if c["placement_id"] == placement_id and c["cycle_status"] == "CLOSED"]
    return sorted(cycles, key=lambda c: c["cycle_index"])


def hours_based_credits(placement):
    target = dec(placement["credit_target_credits"])
    hours = dec(placement["total_verified_hours"])
    blocks = int(hours / HOURS_PER_HALF_CREDIT)
    credits = rh(Decimal(blocks) * Decimal("0.50"), 2)
    return min(target, credits)


def mean_competency(placement_id):
    cycles = closed_cycles(placement_id)
    scored = [c for c in cycles if c.get("competency_score") is not None]
    if not scored:
        return None
    total = sum((dec(c["competency_score"]) for c in scored), ZERO)
    return rh(total / Decimal(len(scored)), 2)


def competency_based_credits(placement):
    target = dec(placement["credit_target_credits"])
    mean = mean_competency(placement["id"])
    if mean is None:
        return rh(ZERO, 2)
    credits = rh(target * mean / MAX_RATING, 2)
    return min(target, credits)


def credit_for_mode(placement):
    if placement["credit_award_mode"] == "HOURS_BASED":
        return rh(hours_based_credits(placement), 2)
    return rh(competency_based_credits(placement), 2)


# --------------------------------------------------------------------------
# reimbursement admin fee (PRD 3.10)
# --------------------------------------------------------------------------

TRANSIT_PASS_BLOCK_CENTS = 4500
TRANSIT_BLOCK_DAYS = 30
MILEAGE_CENTS_PER_MILE = Decimal("50")
GUARDIAN_FACTOR = Decimal("0.65")
SUPERVISOR_STIPEND_PER_CLOSED_CYCLE_CENTS = 7500
TIER_1_MAX_CENTS = 20000
TIER_2_MAX_CENTS = 50000


def reimbursement(placement):
    entries = logged_entries(placement["id"])
    logged_days = len({e["work_date"] for e in entries})
    mode = placement["transportation_mode"]
    miles = dec(placement["commute_round_trip_miles"])

    if mode == "DISTRICT_BUS":
        transport = 0
    elif mode == "PUBLIC_TRANSIT":
        blocks = -(-logged_days // TRANSIT_BLOCK_DAYS)  # ceiling division
        transport = TRANSIT_PASS_BLOCK_CENTS * blocks
    elif mode == "SELF":
        transport = rh_int(MILEAGE_CENTS_PER_MILE * miles * Decimal(logged_days))
    else:  # GUARDIAN
        transport = rh_int(MILEAGE_CENTS_PER_MILE * miles * Decimal(logged_days)
                           * GUARDIAN_FACTOR)

    stipend = SUPERVISOR_STIPEND_PER_CLOSED_CYCLE_CENTS * int(placement["closed_cycle_count"])
    subtotal = transport + stipend

    if subtotal <= TIER_1_MAX_CENTS:
        tier, rate = "TIER_1", Decimal("0.10")
    elif subtotal <= TIER_2_MAX_CENTS:
        tier, rate = "TIER_2", Decimal("0.075")
    else:
        tier, rate = "TIER_3", Decimal("0.05")

    admin_fee = rh_int(Decimal(subtotal) * rate)
    return {
        "transport_cents": transport,
        "stipend_cents": stipend,
        "subtotal_cents": subtotal,
        "tier": tier,
        "admin_fee_cents": admin_fee,
        "total_cents": subtotal + admin_fee,
        "logged_days": logged_days,
    }


# --------------------------------------------------------------------------
# outcome rate (PRD 3.10)
# --------------------------------------------------------------------------

POSITIVE_OUTCOME_TYPES = (
    "EMPLOYED_FULL_TIME",
    "EMPLOYED_PART_TIME",
    "POSTSECONDARY_ENROLLED",
    "APPRENTICESHIP",
    "MILITARY",
)


def outcome_rate(from_date, to_date_):
    cohort = [p for p in db.placements.values()
              if p["lifecycle_status"] == "COMPLETED"
              and p.get("completed_on")
              and from_date <= p["completed_on"] <= to_date_]
    cohort_ids = {p["id"] for p in cohort}
    denominator = len(cohort)
    numerator = sum(1 for o in db.placement_outcomes.values()
                    if o["placement_id"] in cohort_ids and o["counts_positive"])
    if denominator == 0:
        rate = rh(ZERO, 4)
    else:
        rate = rh(Decimal(numerator) / Decimal(denominator), 4)
    return {"numerator": numerator, "denominator": denominator, "positive_rate": rate}


# --------------------------------------------------------------------------
# insurance coverage determination (PRD 3.9)
# --------------------------------------------------------------------------

def insurance_coverage_determination(incident, placement, agreement, partner):
    from validation import iso_date_part
    occurred_date = iso_date_part(incident["occurred_at"])
    comp_current = partner["workers_comp_expires_on"] >= occurred_date

    if comp_current and placement["pay_classification"] == "PAID":
        return "WORKERS_COMP"
    if (placement["pay_classification"] in ("UNPAID", "STIPEND")
            and agreement is not None and agreement["insurance_rider"] is True):
        return "DISTRICT_LIABILITY"
    if not comp_current:
        return "EMPLOYER_LIABILITY_UNINSURED"
    return "NOT_COVERED"


# --------------------------------------------------------------------------
# placement age band (PRD 3.5)
# --------------------------------------------------------------------------

def whole_years(birth_date, on_date):
    birth = to_date(birth_date)
    ref = to_date(on_date)
    years = ref.year - birth.year
    if (ref.month, ref.day) < (birth.month, birth.day):
        years -= 1
    return years


def band_for_age(age):
    if age >= 18:
        return "ADULT_18_PLUS"
    if age >= 16:
        return "MINOR_16_17"
    return "MINOR_14_15"


MINOR_BANDS = ("MINOR_14_15", "MINOR_16_17")
