"""Calculation rules (scaffold section 1.3) and cascade helpers.

All aggregates are computed with Decimal and rounded half-up at the steps the
PRD names. Money is integer cents; hours/census/rates are 2 decimal places;
the milestone composite is 1 decimal place.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import core
from db import DB, clock_dt, clock_date_str, new_id
from util import parse_dt, round2, round1, round0_int

HOURS_LIMIT = Decimal("80.00")
REST_MIN_HOURS = Decimal("8.00")
DAY_OFF_WINDOW_DAYS = 28
DAY_OFF_MIN = 4
AUTO_REMEDIATION_THRESHOLD = 3
BLOCKS_PER_YEAR = 13
PD_WEIGHT = Decimal("2.0")
FACULTY_WEIGHT = Decimal("1.0")
ASSIST_WEIGHT = Decimal("0.5")
ASSIST_CAP_RATIO = Decimal("0.25")
PROBATIONARY_SERIOUS_COUNT = 2

COMPETENCIES = [
    "PATIENT_CARE",
    "MEDICAL_KNOWLEDGE",
    "PROFESSIONALISM",
    "COMMUNICATION",
    "PRACTICE_BASED_LEARNING",
    "SYSTEMS_BASED_PRACTICE",
]

MOON_ATTRIBUTE_STATUSES = ("APPROVED", "ACTIVE", "COMPLETED")
UNRESOLVED_VIOLATION_STATUSES = ("FLAGGED", "ACKNOWLEDGED")
UNRESOLVED_CITATION_STATUSES = (
    "OPEN",
    "RESPONSE_DRAFTED",
    "RESPONSE_SUBMITTED",
    "ESCALATED",
)


# ---------------------------------------------------------------------------
# ISO weeks: Monday 00:00:00Z .. Sunday 24:00:00Z (PRD section 2.4).
# ---------------------------------------------------------------------------

def week_monday(d):
    """Date of the Monday of the ISO week containing date d."""
    return d - timedelta(days=d.weekday())


def week_start_dt(monday_date):
    return datetime(monday_date.year, monday_date.month, monday_date.day,
                    tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# resident_year_stipend (pinned rounding order: round per block FIRST).
# ---------------------------------------------------------------------------

def resident_year_stipend_cents(blended_stipend_cents):
    per_block = round0_int(Decimal(blended_stipend_cents) / BLOCKS_PER_YEAR)
    return per_block * BLOCKS_PER_YEAR


def effective_funded_positions(approved_positions, budget_cents, year_stipend_cents):
    if year_stipend_cents <= 0:
        return approved_positions
    return min(approved_positions, budget_cents // year_stipend_cents)


# ---------------------------------------------------------------------------
# complement_fill — dual variants: headcount (ON_LEAVE counts 1) and funded
# census (ON_LEAVE counts 0.5, 2 dp).
# ---------------------------------------------------------------------------

def complement_fill(comp):
    headcount = 0
    census = Decimal("0")
    for r in DB["residents"].values():
        if (
            r["program_id"] == comp["program_id"]
            and r["pgy_level"] == comp["pgy_level"]
            and r["lifecycle_status"] in ("ACTIVE", "ON_LEAVE")
        ):
            headcount += 1
            census += Decimal("1.0") if r["lifecycle_status"] == "ACTIVE" else Decimal("0.5")
    return headcount, round2(census)


def approved_complement_for(program_id, academic_year_id, pgy_level):
    """The single APPROVED or LOCKED complement row for the triple, if any."""
    for c in DB["complement_approvals"].values():
        if (
            c["program_id"] == program_id
            and c["academic_year_id"] == academic_year_id
            and c["pgy_level"] == pgy_level
            and c["status"] in ("APPROVED", "LOCKED")
        ):
            return c
    return None


def touch_complement_for_resident(resident):
    """Lifecycle events recompute the matching row's fill fields — a mutation
    of the complement row (refreshes updated_at, increments version)."""
    row = approved_complement_for(
        resident["program_id"], resident["entry_academic_year_id"], resident["pgy_level"]
    )
    if row is not None:
        core.touch(row)


# ---------------------------------------------------------------------------
# official_weekly_duty_hours (variants: official = ATTESTED logs only;
# projected = also SUBMITTED logs; moonlighting attribution identical).
# ---------------------------------------------------------------------------

def _weekly_clinical(resident_id, monday_date, include_submitted):
    start = week_start_dt(monday_date)
    end = start + timedelta(days=7)
    statuses = ("ATTESTED", "SUBMITTED") if include_submitted else ("ATTESTED",)
    total = Decimal("0")
    for log in DB["duty_hour_logs"].values():
        if (
            log["resident_id"] == resident_id
            and log["status"] in statuses
            and start <= log["_started"] < end
        ):
            total += log["_duration"]
    return total


def _weekly_moonlighting(resident_id, monday_date, exclude_id=None):
    """Sum of per-request round_half_up(hours_per_week * overlap_days / 7, 2);
    each request's weekly contribution is rounded before summing."""
    start = week_start_dt(monday_date)
    end = start + timedelta(days=7)
    total = Decimal("0")
    for req in DB["moonlighting_requests"].values():
        if req["resident_id"] != resident_id:
            continue
        if exclude_id is not None and req["id"] == exclude_id:
            continue
        if req["status"] not in MOON_ATTRIBUTE_STATUSES:
            continue
        ov_start = max(req["_start"], start)
        ov_end = min(req["_end"], end)
        days = (ov_end - ov_start).days if ov_end > ov_start else 0
        if days <= 0:
            continue
        total += round2(req["_hpw"] * days / Decimal(7))
    return total


def weekly_hours(resident_id, monday_date, projected=False, exclude_id=None):
    clinical = _weekly_clinical(resident_id, monday_date, include_submitted=projected)
    moon = _weekly_moonlighting(resident_id, monday_date, exclude_id=exclude_id)
    return clinical + moon, moon


def rolling_avg(resident_id, monday_date, projected=False, exclude_id=None):
    """Rolling 4-week average over the window of 4 ISO weeks ending with the
    week starting monday_date. The divisor stays 4 even with partial data."""
    total = Decimal("0")
    for i in range(4):
        wk = monday_date - timedelta(days=7 * (3 - i))
        hours, _ = weekly_hours(resident_id, wk, projected=projected, exclude_id=exclude_id)
        total += hours
    return round2(total / Decimal(4))


def duty_hour_summary(resident, week_start_raw):
    ref = week_monday(parse_dt(week_start_raw).date())
    official, moon = weekly_hours(resident["id"], ref, projected=False)
    projected, _ = weekly_hours(resident["id"], ref, projected=True)
    return {
        "resident_id": resident["id"],
        "week_start": ref.strftime("%Y-%m-%d"),
        "official_hours": float(round2(official)),
        "projected_hours": float(round2(projected)),
        "rolling_4wk_avg_official": float(rolling_avg(resident["id"], ref, projected=False)),
        "rolling_4wk_avg_projected": float(rolling_avg(resident["id"], ref, projected=True)),
        "attributed_moonlighting_hours": float(round2(moon)),
    }


# ---------------------------------------------------------------------------
# moonlighting_headroom_check — pinned evaluation order: the candidate is
# excluded from the rolling projected base and added exactly once afterward.
# ---------------------------------------------------------------------------

def headroom_decision_value(candidate):
    resident_id = candidate["resident_id"]
    clock_week = week_monday(clock_dt().date())
    base = rolling_avg(resident_id, clock_week, projected=True, exclude_id=candidate["id"])
    return round2(base + candidate["_hpw"])


# ---------------------------------------------------------------------------
# duty_hour_violation_detection — runs after SUBMITTED -> ATTESTED.
# ---------------------------------------------------------------------------

def _violation_exists(resident_id, rule_code, window_start, window_end):
    for v in DB["duty_hour_violations"].values():
        if (
            v["resident_id"] == resident_id
            and v["status"] in UNRESOLVED_VIOLATION_STATUSES
            and v["rule_code"] == rule_code
            and v["window_start"] == window_start
            and v["window_end"] == window_end
        ):
            return True
    return False


def _create_violation(resident_id, log_id, rule_code, window_start, window_end,
                      measured, threshold):
    if _violation_exists(resident_id, rule_code, window_start, window_end):
        return None
    rec = {
        "id": new_id(),
        "resident_id": resident_id,
        "duty_hour_log_id": log_id,
        "rule_code": rule_code,
        "window_start": window_start,
        "window_end": window_end,
        "_measured": round2(measured),
        "_threshold": round2(threshold),
        "status": "FLAGGED",
        "resolution_note": None,
    }
    core.stamp(rec)
    DB["duty_hour_violations"][rec["id"]] = rec
    return rec


def run_violation_detection(log):
    resident_id = log["resident_id"]
    d = log["_started"].date()

    # Rule HOURS_80_AVG: official rolling average over the 4 ISO weeks ending
    # with the week containing d; strictly greater than 80.00 violates.
    monday = week_monday(d)
    avg = rolling_avg(resident_id, monday, projected=False)
    if avg > HOURS_LIMIT:
        _create_violation(
            resident_id,
            log["id"],
            "HOURS_80_AVG",
            (monday - timedelta(days=21)).strftime("%Y-%m-%d"),
            (monday + timedelta(days=6)).strftime("%Y-%m-%d"),
            avg,
            HOURS_LIMIT,
        )

    # Rule REST_8H: the ATTESTED log with the greatest ended_at strictly before
    # this log's started_at (tie-break: latest created_at); gap < 8.00 violates.
    prev = None
    for other in DB["duty_hour_logs"].values():
        if other["resident_id"] != resident_id or other["status"] != "ATTESTED":
            continue
        if other["_ended"] < log["_started"]:
            if prev is None or (other["_ended"], other["_seq"]) > (prev["_ended"], prev["_seq"]):
                prev = other
    if prev is not None:
        gap_seconds = Decimal(str((log["_started"] - prev["_ended"]).total_seconds()))
        gap_hours = round2(gap_seconds / Decimal(3600))
        if gap_hours < REST_MIN_HOURS:
            _create_violation(
                resident_id,
                log["id"],
                "REST_8H",
                prev["ended_at"],
                log["started_at"],
                gap_hours,
                REST_MIN_HOURS,
            )

    # Rule DAY_OFF_4_IN_28: distinct worked dates (by started_at date) in the
    # 28 calendar dates [d-27, d]; days_off = 28 - worked; < 4 violates.
    window_start_date = d - timedelta(days=DAY_OFF_WINDOW_DAYS - 1)
    worked = set()
    for other in DB["duty_hour_logs"].values():
        if other["resident_id"] != resident_id or other["status"] != "ATTESTED":
            continue
        od = other["_started"].date()
        if window_start_date <= od <= d:
            worked.add(od)
    days_off = DAY_OFF_WINDOW_DAYS - len(worked)
    if days_off < DAY_OFF_MIN:
        _create_violation(
            resident_id,
            log["id"],
            "DAY_OFF_4_IN_28",
            window_start_date.strftime("%Y-%m-%d"),
            d.strftime("%Y-%m-%d"),
            Decimal(days_off),
            Decimal(DAY_OFF_MIN),
        )


def unresolved_violations_in_active_year(resident):
    """Unresolved violations whose triggering log started inside an ACTIVE
    academic year of the resident's program."""
    active_years = [
        y for y in DB["academic_years"].values()
        if y["program_id"] == resident["program_id"] and y["status"] == "ACTIVE"
    ]
    count = 0
    for v in DB["duty_hour_violations"].values():
        if v["resident_id"] != resident["id"]:
            continue
        if v["status"] not in UNRESOLVED_VIOLATION_STATUSES:
            continue
        log = DB["duty_hour_logs"].get(v["duty_hour_log_id"])
        if log is None:
            continue
        for y in active_years:
            if y["_start"] <= log["_started"] < y["_end"]:
                count += 1
                break
    return count


def maybe_auto_remediate(resident):
    """Aftermath of a detection pass: >= 3 unresolved violations in the current
    ACTIVE year and no ACTIVE plan -> auto-create a remediation plan."""
    if unresolved_violations_in_active_year(resident) < AUTO_REMEDIATION_THRESHOLD:
        return None
    for p in DB["remediation_plans"].values():
        if p["resident_id"] == resident["id"] and p["status"] == "ACTIVE":
            return None
    start = clock_dt().date()
    end = start + timedelta(days=90)
    plan = {
        "id": new_id(),
        "resident_id": resident["id"],
        "ccc_review_id": None,
        "trigger_source": "DUTY_HOUR_VIOLATIONS",
        "goals": "Automatic remediation: repeated duty-hour violations",
        "start_date": start.strftime("%Y-%m-%d"),
        "end_date": end.strftime("%Y-%m-%d"),
        "outcome": None,
        "status": "ACTIVE",
        "cancel_reason": None,
    }
    core.stamp(plan)
    DB["remediation_plans"][plan["id"]] = plan
    recompute_standing(resident)
    return plan


# ---------------------------------------------------------------------------
# standing_resolution + the moonlighting sweep (PRD section 3.8).
# ---------------------------------------------------------------------------

def recompute_standing(resident):
    open_probation = any(
        c["resident_id"] == resident["id"] and c["status"] in ("ACTIVE", "DISMISSAL_RECOMMENDED")
        for c in DB["probation_cases"].values()
    )
    active_plan = any(
        p["resident_id"] == resident["id"] and p["status"] == "ACTIVE"
        for p in DB["remediation_plans"].values()
    )
    if open_probation:
        new = "ON_PROBATION"
    elif active_plan:
        new = "UNDER_REMEDIATION"
    else:
        new = "GOOD_STANDING"
    old = resident["standing_status"]
    if new != old:
        resident["standing_status"] = new
        core.touch(resident)
        if old == "GOOD_STANDING":
            # Standing leaves GOOD_STANDING: moonlighting sweep runs.
            moonlighting_sweep(resident)


def moonlighting_sweep(resident):
    """Every APPROVED or ACTIVE request of the resident -> REVOKED with
    decision_reason STANDING_CHANGE. SUBMITTED requests are left untouched."""
    for req in DB["moonlighting_requests"].values():
        if req["resident_id"] != resident["id"]:
            continue
        if req["status"] in ("APPROVED", "ACTIVE"):
            req["status"] = "REVOKED"
            req["decision_reason"] = "STANDING_CHANGE"
            core.touch(req)


# ---------------------------------------------------------------------------
# program_accreditation_status (threshold over unresolved SERIOUS citations).
# ---------------------------------------------------------------------------

def recompute_program_status(program):
    serious_unresolved = sum(
        1
        for c in DB["accreditation_citations"].values()
        if c["program_id"] == program["id"]
        and c["status"] in UNRESOLVED_CITATION_STATUSES
        and c["severity"] == "SERIOUS"
    )
    if serious_unresolved >= PROBATIONARY_SERIOUS_COUNT:
        new = "PROBATIONARY"
    elif serious_unresolved >= 1:
        new = "CONTINUED_WITH_WARNING"
    else:
        new = "CONTINUED"
    if new != program["accreditation_status"]:
        program["accreditation_status"] = new
        core.touch(program)


# ---------------------------------------------------------------------------
# case_log_progress — assist weight 0.5 capped at 25% of required_count.
# ---------------------------------------------------------------------------

def case_progress(resident):
    requirements = [
        q for q in DB["case_requirements"].values()
        if q["program_id"] == resident["program_id"]
    ]
    requirements.sort(key=lambda q: q["_seq"])
    entries = []
    all_met = True
    for q in requirements:
        verified_primary = 0
        verified_assist = 0
        for log in DB["procedure_case_logs"].values():
            if (
                log["resident_id"] == resident["id"]
                and log["status"] == "VERIFIED"
                and log["procedure_category"] == q["procedure_category"]
            ):
                if log["role"] == "SURGEON":
                    verified_primary += 1
                elif log["role"] == "ASSIST":
                    verified_assist += 1
        assist_credit = min(
            round2(Decimal(verified_assist) * ASSIST_WEIGHT),
            round2(ASSIST_CAP_RATIO * q["required_count"]),
        )
        effective_cases = round2(Decimal(verified_primary) + assist_credit)
        met = (
            effective_cases >= Decimal(q["required_count"])
            and verified_primary >= q["required_primary_count"]
        )
        all_met = all_met and met
        entries.append({
            "requirement_id": q["id"],
            "procedure_category": q["procedure_category"],
            "required_count": q["required_count"],
            "required_primary_count": q["required_primary_count"],
            "verified_primary": verified_primary,
            "verified_assist": verified_assist,
            "assist_credit": float(assist_credit),
            "effective_cases": float(effective_cases),
            "requirement_met": met,
        })
    return {
        "resident_id": resident["id"],
        "requirements": entries,
        "all_met": all_met,
    }


# ---------------------------------------------------------------------------
# milestone_composite_level — PD weight 2.0 vs FACULTY 1.0, rounded once at
# the end to 1 decimal place.
# ---------------------------------------------------------------------------

def milestone_composite_snapshot(resident_id, academic_year_id, reporting_period):
    evals = [
        e for e in DB["milestone_evaluations"].values()
        if e["resident_id"] == resident_id
        and e["academic_year_id"] == academic_year_id
        and e["reporting_period"] == reporting_period
    ]
    snapshot = {}
    for comp in COMPETENCIES:
        num = Decimal("0")
        den = Decimal("0")
        for e in evals:
            w = PD_WEIGHT if e["evaluator_role"] == "PROGRAM_DIRECTOR" else FACULTY_WEIGHT
            level = e["_ratings"][comp]
            num += Decimal(level) * w
            den += w
        snapshot[comp] = float(round1(num / den)) if den > 0 else None
    return snapshot
