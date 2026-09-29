"""The thirteen calculation rules of SCAFFOLD section 1.3 / PRD section 3.

Every ``source: computed`` field is derived here, lazily, from the current rows;
nothing derived is cached on a row, so a logical-clock advance immediately
changes every clock-dependent figure without touching storage.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db

# ------------------------------------------------------------------- constants
ZERO = Decimal("0.00")
STANDARD_WORK_DAYS_PER_WEEK = Decimal(5)
FULLY_UNAVAILABLE_HOURS = Decimal("0.00")

TIER_MULTIPLIER = {"GREEN": Decimal("1.25"), "AMBER": Decimal("1.15"), "RED": Decimal("1.00")}
ABSOLUTE_CEILING_MULTIPLIER = Decimal("1.40")

DAYS_PER_WEEK = 7
ONE_DAY = timedelta(days=1)

OFFSHORE_REVIEW_RATIO = Decimal("0.20")
MIN_REVIEW_BLOCK_HOURS = Decimal("2.00")
REWORK_REVIEW_HOURS = Decimal("1.00")
MAX_REWORK_CYCLES = 2

LEVEL_MATCH_WEIGHT = Decimal(40)
INDUSTRY_WEIGHT = Decimal(30)
SLACK_WEIGHT = Decimal(30)

RATE_MODEL_FACTOR = {
    "ONSHORE_STANDARD": Decimal("1.00"),
    "OFFSHORE_SHARED_SERVICE": Decimal("0.55"),
}
PERCENT_SCALE = Decimal(100)

DECAY_WEIGHTS = (Decimal("1.00"), Decimal("0.75"), Decimal("0.50"), Decimal("0.25"))
DECAY_WEIGHT_SUM = Decimal("2.50")
BAND_ELEVATED_AT = Decimal("3.00")
BAND_HIGH_AT = Decimal("6.00")
WEEK_WINDOW = 4

HIGH_COMPLETION_PCT = Decimal("60.00")
HIGH_DAYS = 30
MEDIUM_COMPLETION_PCT = Decimal("90.00")
MEDIUM_DAYS = 60
BLOCK_ESCALATION_COUNT = 2

ROTATION_LIMIT_PIE = 5
ROTATION_LIMIT_STANDARD = 7

TIME_ENTRY_TOLERANCE = Decimal("1.25")

# staffing_status values that occupy capacity (RELEASED is excluded everywhere)
LIVE_STAFFING = ("PROPOSED", "CONFIRMED", "ACTIVE", "COMPLETED")
FINAL_LOGGED_STAFFING = ("CONFIRMED", "ACTIVE", "COMPLETED")


# ------------------------------------------------------------------- primitives
def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def r2(value):
    return D(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def r4(value):
    return D(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def iso_week_start(day):
    """The Monday on or before ``day`` (ISO weeks begin Monday)."""
    return day - timedelta(days=day.weekday())


def current_week_start():
    return iso_week_start(db.current_date())


def last_worked_day(assignment):
    return assignment["end_date"] - timedelta(days=1)


def occupied_dates(assignment):
    day = assignment["start_date"]
    while day < assignment["end_date"]:
        yield day
        day += timedelta(days=1)


def occupies(assignment, day):
    return assignment["start_date"] <= day < assignment["end_date"]


def overlap_days(assignment, week_start):
    """Occupied dates of the assignment that fall inside the ISO week."""
    lo = max(assignment["start_date"], week_start)
    hi = min(last_worked_day(assignment), week_start + timedelta(days=DAYS_PER_WEEK - 1))
    if hi < lo:
        return 0
    return (hi - lo).days + 1


def ranges_intersect(a_start, a_end, b_start, b_end):
    return a_start <= b_end and b_start <= a_end


# ---------------------------------------------------------------- row selectors
def assignments_of_phase(phase_id, statuses=None):
    rows = [a for a in db.assignments.values() if a["engagement_phase_id"] == phase_id]
    if statuses is not None:
        rows = [a for a in rows if a["staffing_status"] in statuses]
    return db.by_seq(rows)


def phases_of_engagement(engagement_id):
    return db.by_seq([p for p in db.phases.values() if p["engagement_id"] == engagement_id])


def assignments_of_staff(staff_id, statuses=None):
    rows = [a for a in db.assignments.values() if a["staff_member_id"] == staff_id]
    if statuses is not None:
        rows = [a for a in rows if a["staffing_status"] in statuses]
    return db.by_seq(rows)


def time_entries_of_assignment(assignment_id):
    return db.by_seq(
        [t for t in db.time_entries.values() if t["assignment_id"] == assignment_id]
    )


def engagement_of_phase(phase):
    return db.engagements.get(phase["engagement_id"])


def engagement_of_assignment(assignment):
    phase = db.phases.get(assignment["engagement_phase_id"])
    if phase is None:
        return None
    return db.engagements.get(phase["engagement_id"])


def assignments_of_engagement(engagement_id, statuses=None):
    phase_ids = {p["id"] for p in db.phases.values() if p["engagement_id"] == engagement_id}
    rows = [a for a in db.assignments.values() if a["engagement_phase_id"] in phase_ids]
    if statuses is not None:
        rows = [a for a in rows if a["staffing_status"] in statuses]
    return db.by_seq(rows)


def exceptions_of_staff(staff_id):
    return db.by_seq(
        [e for e in db.availability_exceptions.values() if e["staff_member_id"] == staff_id]
    )


# =============================================================================
# 1. assignment_daily_hours
# =============================================================================
def calendar_day_count(start_date, end_date):
    return (end_date - start_date).days


def assignment_daily_hours(allocated_hours, day_count):
    return r2(D(allocated_hours) / Decimal(day_count))


# =============================================================================
# 3. effective_weekly_cap  (evaluated before daily capacity: pinned order)
# =============================================================================
def logged_hours_in_week(staff_id, week_start):
    """Sum of TimeEntry.hours in one ISO week over the staff member's
    non-RELEASED assignments; all three entry types count."""
    total = ZERO
    week_end = week_start + timedelta(days=DAYS_PER_WEEK - 1)
    for entry in db.time_entries.values():
        assignment = db.assignments.get(entry["assignment_id"])
        if assignment is None or assignment["staff_member_id"] != staff_id:
            continue
        if assignment["staffing_status"] == "RELEASED":
            continue
        if week_start <= entry["work_date"] <= week_end:
            total += D(entry["hours"])
    return r2(total)


def approved_waiver_hours(staff_id, week_start):
    total = ZERO
    for waiver in db.waivers.values():
        if (
            waiver["staff_member_id"] == staff_id
            and waiver["week_start_date"] == week_start
            and waiver["status"] == "APPROVED"
        ):
            total += D(waiver["extra_hours_allowance"])
    return r2(total)


def burnout_tier(staff, week_start):
    base = D(staff["base_weekly_cap_hours"])
    prior_logged = logged_hours_in_week(staff["id"], week_start - timedelta(days=DAYS_PER_WEEK))
    utilization = r4(prior_logged / base)
    if utilization <= Decimal("1.0000"):
        return "GREEN", utilization
    if utilization <= Decimal("1.2500"):
        return "AMBER", utilization
    return "RED", utilization


def effective_weekly_cap(staff, week_start):
    base = D(staff["base_weekly_cap_hours"])
    tier, _ = burnout_tier(staff, week_start)
    multiplier = TIER_MULTIPLIER[tier]
    allowance = approved_waiver_hours(staff["id"], week_start)
    raw_cap = r2(base * multiplier)
    ceiling = r2(base * ABSOLUTE_CEILING_MULTIPLIER)
    return r2(min(raw_cap + allowance, ceiling))


# =============================================================================
# 2. staff_daily_capacity
# =============================================================================
def exception_covering(staff_id, day):
    for exception in exceptions_of_staff(staff_id):
        if exception["start_date"] <= day <= exception["end_date"]:
            return exception
    return None


def daily_capacity_baseline(staff, day):
    cap = effective_weekly_cap(staff, iso_week_start(day))
    return r2(cap / STANDARD_WORK_DAYS_PER_WEEK)


def capacity_on(staff, day):
    exception = exception_covering(staff["id"], day)
    if exception is not None:
        return D(exception["available_hours_per_day"])
    return daily_capacity_baseline(staff, day)


def booked_on(staff_id, day, exclude_ids=()):
    total = ZERO
    for assignment in db.assignments.values():
        if assignment["staff_member_id"] != staff_id:
            continue
        if assignment["id"] in exclude_ids:
            continue
        if assignment["staffing_status"] not in LIVE_STAFFING:
            continue
        if occupies(assignment, day):
            total += D(assignment["daily_hours"])
    return r2(total)


def daily_capacity_hours(staff):
    """The surfaced field: baseline for the ISO week of the logical clock."""
    cap = effective_weekly_cap(staff, current_week_start())
    return r2(cap / STANDARD_WORK_DAYS_PER_WEEK)


def daily_capacity_admissible(staff, start_date, end_date, candidate_daily, exclude_ids=()):
    day = start_date
    while day < end_date:
        if booked_on(staff["id"], day, exclude_ids) + candidate_daily > capacity_on(staff, day):
            return False
        day += timedelta(days=1)
    return True


def fully_unavailable_date(staff_id, start_date, end_date):
    day = start_date
    while day < end_date:
        exception = exception_covering(staff_id, day)
        if exception is not None and D(exception["available_hours_per_day"]) == FULLY_UNAVAILABLE_HOURS:
            return day
        day += timedelta(days=1)
    return None


# =============================================================================
# 4. weekly_committed_hours
# =============================================================================
def committed_hours(staff_id, week_start, exclude_ids=(), only_ids=None):
    total = ZERO
    for assignment in db.assignments.values():
        if assignment["staff_member_id"] != staff_id:
            continue
        if assignment["id"] in exclude_ids:
            continue
        if only_ids is not None and assignment["id"] not in only_ids:
            continue
        if assignment["staffing_status"] not in LIVE_STAFFING:
            continue
        days = overlap_days(assignment, week_start)
        if days:
            total += D(assignment["daily_hours"]) * Decimal(days)
    return r2(total)


def committed_hours_current_week(staff):
    return committed_hours(staff["id"], current_week_start())


def touched_weeks(start_date, end_date):
    """ISO week starts touched by the half-open interval [start_date, end_date)."""
    weeks = []
    day = iso_week_start(start_date)
    last = iso_week_start(end_date - timedelta(days=1))
    while day <= last:
        weeks.append(day)
        day += timedelta(days=DAYS_PER_WEEK)
    return weeks


def weekly_cap_admissible(staff, start_date, end_date, candidate_daily, exclude_ids=()):
    fake = {"start_date": start_date, "end_date": end_date}
    for week_start in touched_weeks(start_date, end_date):
        contribution = candidate_daily * Decimal(overlap_days(fake, week_start))
        existing = committed_hours(staff["id"], week_start, exclude_ids)
        if existing + contribution > effective_weekly_cap(staff, week_start):
            return False
    return True


def workload_status(staff):
    committed = committed_hours_current_week(staff)
    base = D(staff["base_weekly_cap_hours"])
    effective = effective_weekly_cap(staff, current_week_start())
    if committed <= base:
        return "GREEN"
    if committed <= effective:
        return "AMBER"
    return "RED"


# =============================================================================
# 5. offshore_review_charge
# =============================================================================
def review_charge_base(allocated_hours):
    return max(r2(D(allocated_hours) * OFFSHORE_REVIEW_RATIO), MIN_REVIEW_BLOCK_HOURS)


def review_hours_for(allocated_hours, rework_cycles):
    base = review_charge_base(allocated_hours)
    return r2(base + Decimal(rework_cycles) * REWORK_REVIEW_HOURS)


def find_review_window(reviewer_staff_id, charge_week):
    for window in db.by_seq(list(db.review_windows.values())):
        if (
            window["reviewer_staff_id"] == reviewer_staff_id
            and window["week_start_date"] == charge_week
        ):
            return window
    return None


# =============================================================================
# 6. review_window_load
# =============================================================================
def committed_review_hours(window_id, exclude_ids=()):
    total = ZERO
    for assignment in db.assignments.values():
        if assignment.get("review_capacity_window_id") != window_id:
            continue
        if assignment["id"] in exclude_ids:
            continue
        if assignment["staffing_status"] not in LIVE_STAFFING:
            continue
        total += D(assignment["review_hours_charged"])
    return r2(total)


def remaining_review_hours(window):
    return r2(D(window["review_capacity_hours"]) - committed_review_hours(window["id"]))


# =============================================================================
# 9. burnout_risk_score  +  turnover_risk_band
# =============================================================================
def _decayed(overages):
    weighted = ZERO
    for weight, overage in zip(DECAY_WEIGHTS, overages):
        weighted += weight * overage
    return r2(weighted / DECAY_WEIGHT_SUM)


def burnout_risk_score_actual(staff):
    base = D(staff["base_weekly_cap_hours"])
    w0 = current_week_start()
    overages = []
    for i in range(WEEK_WINDOW):
        week_start = w0 - timedelta(days=DAYS_PER_WEEK * i)
        logged = logged_hours_in_week(staff["id"], week_start)
        overages.append(max(ZERO, r2(logged - base)))
    return _decayed(overages)


def burnout_risk_score_committed(staff):
    base = D(staff["base_weekly_cap_hours"])
    w0 = current_week_start()
    overages = []
    for i in range(WEEK_WINDOW):
        week_start = w0 + timedelta(days=DAYS_PER_WEEK * i)
        committed = committed_hours(staff["id"], week_start)
        overages.append(max(ZERO, r2(committed - base)))
    return _decayed(overages)


def band_for_score(worst):
    if worst < BAND_ELEVATED_AT:
        return "LOW"
    if worst < BAND_HIGH_AT:
        return "ELEVATED"
    return "HIGH"


def turnover_risk_band(staff):
    worst = max(burnout_risk_score_actual(staff), burnout_risk_score_committed(staff))
    return band_for_score(worst)


def review_capable(staff):
    return staff["level"] in ("MANAGER", "PARTNER") and staff["service_center"] == "DOMESTIC"


# =============================================================================
# 10. phase_staffing_derivation
# =============================================================================
def phase_staffed_hours(phase):
    total = ZERO
    for assignment in db.assignments.values():
        if assignment["engagement_phase_id"] != phase["id"]:
            continue
        if assignment["staffing_status"] not in LIVE_STAFFING:
            continue
        total += D(assignment["allocated_hours"])
    return r2(total)


def phase_unstaffed_hours(phase):
    staffed = phase_staffed_hours(phase)
    return r2(max(ZERO, D(phase["expected_hours"]) - staffed))


def derived_phase_status(phase):
    """None when the phase is frozen (IN_PROGRESS / COMPLETE)."""
    if phase["staffing_status"] in ("IN_PROGRESS", "COMPLETE"):
        return None
    staffed = phase_staffed_hours(phase)
    if staffed == ZERO:
        return "NOT_STAFFED"
    if staffed >= D(phase["expected_hours"]):
        return "FULLY_STAFFED"
    return "PARTIALLY_STAFFED"


# =============================================================================
# 11. engagement_staffing_completion
# =============================================================================
def staffing_completion_pct(engagement):
    phases = phases_of_engagement(engagement["id"])
    expected_total = r2(sum((D(p["expected_hours"]) for p in phases), ZERO))
    staffed_total = r2(sum((phase_staffed_hours(p) for p in phases), ZERO))
    if expected_total == ZERO:
        return ZERO
    return r2(min(staffed_total, expected_total) / expected_total * PERCENT_SCALE)


# =============================================================================
# 12. engagement_schedule_risk
# =============================================================================
def schedule_risk_band(engagement):
    completion = staffing_completion_pct(engagement)
    days_to_deadline = (engagement["deadline_date"] - db.current_date()).days
    if engagement["client_block_count"] >= BLOCK_ESCALATION_COUNT:
        return "HIGH"
    if completion < HIGH_COMPLETION_PCT and days_to_deadline <= HIGH_DAYS:
        return "HIGH"
    if completion < MEDIUM_COMPLETION_PCT and days_to_deadline <= MEDIUM_DAYS:
        return "MEDIUM"
    return "LOW"


# =============================================================================
# 13. partner_rotation_check
# =============================================================================
def partner_rotation_limit_years(client):
    return ROTATION_LIMIT_PIE if client["public_interest_entity"] else ROTATION_LIMIT_STANDARD


def consecutive_partner_years(client_id, partner_staff_id, busy_season_year):
    run = 0
    year = busy_season_year - 1
    while True:
        found = any(
            e["client_id"] == client_id
            and e["engagement_partner_staff_id"] == partner_staff_id
            and e["busy_season_year"] == year
            for e in db.engagements.values()
        )
        if not found:
            break
        run += 1
        year -= 1
    return run + 1


def engagement_count(client_id):
    return sum(
        1
        for e in db.engagements.values()
        if e["client_id"] == client_id and e["status"] != "DELIVERED"
    )


# =============================================================================
# 8. engagement_realization
# =============================================================================
def effective_rate(assignment):
    staff = db.staff_members.get(assignment["staff_member_id"])
    if staff is None:
        return ZERO
    return r2(D(staff["hourly_bill_rate"]) * RATE_MODEL_FACTOR[assignment["rate_model"]])


def realization(engagement):
    """Both variants plus the split-by-staffing-model figures of the read."""
    provisional_rows = assignments_of_engagement(engagement["id"], LIVE_STAFFING)

    standard_provisional = ZERO
    onshore_value = ZERO
    offshore_value = ZERO
    committed_total = ZERO
    for assignment in provisional_rows:
        line = r2(D(assignment["allocated_hours"]) * effective_rate(assignment))
        standard_provisional += line
        committed_total += D(assignment["allocated_hours"])
        if assignment["rate_model"] == "ONSHORE_STANDARD":
            onshore_value += line
        else:
            offshore_value += line
    standard_provisional = r2(standard_provisional)

    final_rows = assignments_of_engagement(engagement["id"], FINAL_LOGGED_STAFFING)
    final_ids = {a["id"] for a in final_rows}
    rate_by_assignment = {a["id"]: effective_rate(a) for a in final_rows}

    standard_final = ZERO
    logged_total = ZERO
    for entry in db.by_seq(list(db.time_entries.values())):
        if entry["assignment_id"] not in final_ids:
            continue
        standard_final += r2(D(entry["hours"]) * rate_by_assignment[entry["assignment_id"]])
        logged_total += D(entry["hours"])
    standard_final = r2(standard_final)

    budget = D(engagement["budget_fee_amount"])
    pct_provisional = (
        ZERO if standard_provisional == ZERO else r2(budget / standard_provisional * PERCENT_SCALE)
    )
    pct_final = ZERO if standard_final == ZERO else r2(budget / standard_final * PERCENT_SCALE)

    return {
        "standard_value_provisional": standard_provisional,
        "realization_pct_provisional": pct_provisional,
        "standard_value_final": standard_final,
        "realization_pct_final": pct_final,
        "onshore_standard_value": r2(onshore_value),
        "offshore_standard_value": r2(offshore_value),
        "committed_hours_total": r2(committed_total),
        "logged_hours_total": r2(logged_total),
    }


def realization_pct_provisional(engagement):
    return realization(engagement)["realization_pct_provisional"]


def realization_pct_final(engagement):
    return realization(engagement)["realization_pct_final"]


# =============================================================================
# 7. staff_fit_score  (auto-staffing selector)
# =============================================================================
def independence_conflict(client_id, staff_id, start_date, end_date):
    """An ACTIVE restriction whose closed window shares a date with the booking's
    occupied dates [start_date, end_date - 1 day]."""
    booking_last = end_date - timedelta(days=1)
    for restriction in db.by_seq(list(db.restrictions.values())):
        if restriction["status"] != "ACTIVE":
            continue
        if restriction["client_id"] != client_id or restriction["staff_member_id"] != staff_id:
            continue
        if ranges_intersect(
            restriction["effective_start_date"],
            restriction["effective_end_date"],
            start_date,
            booking_last,
        ):
            return restriction
    return None


def eligible_candidates(phase, engagement, start_date, end_date, allocated_hours):
    day_count = calendar_day_count(start_date, end_date)
    candidate_daily = assignment_daily_hours(allocated_hours, day_count)
    pool = []
    for staff in db.by_seq(list(db.staff_members.values())):
        if staff["level"] != phase["required_level"]:
            continue
        required_spec = phase["required_industry_specialization"]
        if required_spec is not None and staff["industry_specialization"] != required_spec:
            continue
        if phase["requires_cpa_licensed"] and not staff["cpa_licensed"]:
            continue
        if staff["service_center"] != "DOMESTIC":
            continue
        if independence_conflict(engagement["client_id"], staff["id"], start_date, end_date):
            continue
        if turnover_risk_band(staff) == "HIGH":
            continue
        if not daily_capacity_admissible(staff, start_date, end_date, candidate_daily):
            continue
        if not weekly_cap_admissible(staff, start_date, end_date, candidate_daily):
            continue
        pool.append(staff)
    return pool, candidate_daily


def fit_score(staff, phase, start_date):
    week_start = iso_week_start(start_date)
    remaining_week = r2(
        effective_weekly_cap(staff, week_start) - committed_hours(staff["id"], week_start)
    )
    unstaffed = phase_unstaffed_hours(phase)
    slack_ratio = min(Decimal("1.0000"), r4(remaining_week / unstaffed))
    industry = INDUSTRY_WEIGHT if phase["required_industry_specialization"] is not None else Decimal(0)
    return r2(LEVEL_MATCH_WEIGHT + industry + SLACK_WEIGHT * slack_ratio)


def select_candidate(phase, engagement, start_date, end_date, allocated_hours):
    pool, candidate_daily = eligible_candidates(
        phase, engagement, start_date, end_date, allocated_hours
    )
    if not pool:
        return None, None, candidate_daily
    scored = [(staff, fit_score(staff, phase, start_date)) for staff in pool]
    scored.sort(key=lambda item: (-item[1], D(item[0]["hourly_bill_rate"]), item[0]["_seq"]))
    best_staff, best_score = scored[0]
    return best_staff, best_score, candidate_daily


# =============================================================================
# 13b. reschedule_projection
# =============================================================================
def projection_target_phase(engagement_id):
    phases = phases_of_engagement(engagement_id)
    if not phases:
        return None
    return sorted(phases, key=lambda p: (-p["window_start_date"].toordinal(), p["_seq"]))[0]


def reschedule_projection(plan, engagement):
    phases = phases_of_engagement(engagement["id"])
    target = projection_target_phase(engagement["id"])
    shift = timedelta(days=plan["shift_days"])
    added = D(plan["added_hours"])

    dropped = 0
    kept_by_phase = {p["id"]: [] for p in phases}
    kept_all = []
    for phase in phases:
        shifted_start = phase["window_start_date"] + shift
        shifted_end = phase["window_end_date"] + shift
        for assignment in assignments_of_phase(phase["id"]):
            if assignment["staffing_status"] in ("PROPOSED", "CONFIRMED"):
                keep = (
                    shifted_start <= assignment["start_date"]
                    and last_worked_day(assignment) <= shifted_end
                )
                if not keep:
                    dropped += 1
                    continue
            elif assignment["staffing_status"] == "RELEASED":
                continue
            kept_by_phase[phase["id"]].append(assignment)
            kept_all.append(assignment)

    unstaffed_total = ZERO
    for phase in phases:
        expected = D(phase["expected_hours"])
        if target is not None and phase["id"] == target["id"]:
            expected += added
        staffed = r2(sum((D(a["allocated_hours"]) for a in kept_by_phase[phase["id"]]), ZERO))
        unstaffed_total += max(ZERO, expected - staffed)
    projected_unstaffed = r2(unstaffed_total)

    kept_ids = {a["id"] for a in kept_all}
    breach_pairs = set()
    for assignment in kept_all:
        staff = db.staff_members.get(assignment["staff_member_id"])
        if staff is None:
            continue
        for week_start in touched_weeks(assignment["start_date"], assignment["end_date"]):
            key = (staff["id"], week_start)
            if key in breach_pairs:
                continue
            load = committed_hours(staff["id"], week_start, only_ids=kept_ids)
            if load > effective_weekly_cap(staff, week_start):
                breach_pairs.add(key)

    standard_value = r2(
        sum((r2(D(a["allocated_hours"]) * effective_rate(a)) for a in kept_all), ZERO)
    )
    budget = D(engagement["budget_fee_amount"])
    projected_pct = (
        ZERO if standard_value == ZERO else r2(budget / standard_value * PERCENT_SCALE)
    )

    return {
        "target_phase_id": None if target is None else target["id"],
        "projected_unstaffed_hours": projected_unstaffed,
        "projected_dropped_assignment_count": dropped,
        "projected_cap_breach_count": len(breach_pairs),
        "projected_realization_pct": projected_pct,
    }


def simulation_stale(plan):
    engagement = db.engagements.get(plan["engagement_id"])
    pinned = plan["simulated_at_engagement_version"]
    if pinned is None or engagement is None:
        return True
    return pinned != engagement["version"]
