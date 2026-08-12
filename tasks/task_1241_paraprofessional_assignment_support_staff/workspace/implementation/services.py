"""Business logic: derived fields, costing, cascades, selector, plan close.

Implements SCAFFOLD.yaml §1.2 state machines, §1.3 calculations, and the
PRD §3 workflows. All money math uses Decimal with ROUND_HALF_UP (PRD §2.6).
"""
from datetime import timedelta

import db
from errors import (
    ERR_ABSENCE_NOT_FOUND, ERR_ALLOCATION_NOT_FOUND, ERR_ASSIGNMENT_NOT_FOUND,
    ERR_BACKFILL_NOT_FOUND, ERR_BUILDING_NOT_FOUND, ERR_CHANGE_ORDER_NOT_FOUND,
    ERR_COVERAGE_PLAN_NOT_FOUND, ERR_EVALUATION_NOT_FOUND, ERR_FORMULA_NOT_FOUND,
    ERR_PARA_NOT_FOUND, ERR_PLAN_NOT_FOUND, ERR_STUDENT_NOT_FOUND,
    ERR_TIMESHEET_NOT_FOUND, ApiError,
)
from util import WEEKDAYS, dec, iso_ts, new_id, parse_date, rhu, week_monday

QUAL_DIFFERENTIAL = {
    "NONE": 0,
    "BEHAVIOR_SUPPORT": 150,
    "MEDICAL_DELEGATION": 200,
    "SIGN_LANGUAGE": 250,
}
SERVICE_STIPEND_ONE_TO_ONE = 100

NON_TERMINAL_ABSENCE = ("REPORTED", "BACKFILL_PENDING", "ESCALATED")


# ---------------------------------------------------------------------------
# Lookup helpers (existence validation -> dedicated 404s)
# ---------------------------------------------------------------------------

def _get(store, rid, error_id, label):
    rec = db.STORE[store].get(rid)
    if rec is None:
        raise ApiError(error_id, 404, "%s not found: %s" % (label, rid))
    return rec


def get_plan(rid):
    return _get("plans", rid, ERR_PLAN_NOT_FOUND, "StaffingPlan")


def get_building(rid):
    return _get("buildings", rid, ERR_BUILDING_NOT_FOUND, "Building")


def get_student(rid):
    return _get("students", rid, ERR_STUDENT_NOT_FOUND, "Student")


def get_para(rid):
    return _get("paras", rid, ERR_PARA_NOT_FOUND, "Paraprofessional")


def get_sco(rid):
    return _get("scos", rid, ERR_CHANGE_ORDER_NOT_FOUND, "ServiceChangeOrder")


def get_assignment(rid):
    return _get("assignments", rid, ERR_ASSIGNMENT_NOT_FOUND, "Assignment")


def get_coverage_plan(rid):
    return _get("coverage_plans", rid, ERR_COVERAGE_PLAN_NOT_FOUND, "CoveragePlan")


def get_absence(rid):
    return _get("absences", rid, ERR_ABSENCE_NOT_FOUND, "AbsenceReport")


def get_backfill(rid):
    return _get("backfills", rid, ERR_BACKFILL_NOT_FOUND, "BackfillAssignment")


def get_timesheet(rid):
    return _get("timesheets", rid, ERR_TIMESHEET_NOT_FOUND, "TimesheetEntry")


def get_evaluation(rid):
    return _get("evaluations", rid, ERR_EVALUATION_NOT_FOUND, "Evaluation")


def get_formula(rid):
    return _get("formulas", rid, ERR_FORMULA_NOT_FOUND, "AllocationFormula")


def get_allocation(rid):
    return _get("allocations", rid, ERR_ALLOCATION_NOT_FOUND, "FundingAllocation")


# ---------------------------------------------------------------------------
# Record plumbing
# ---------------------------------------------------------------------------

def stamp_new(rec):
    ts = iso_ts(db.now())
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version (PRD §2.5)."""
    rec["updated_at"] = iso_ts(db.now())
    rec["version"] += 1


def sorted_records(store_name):
    return sorted(
        db.STORE[store_name].values(),
        key=lambda r: (r["created_at"], r["_seq"]),
    )


# ---------------------------------------------------------------------------
# Derived fields
# ---------------------------------------------------------------------------

def current_week_bounds():
    monday = week_monday(db.now().date())
    return monday, monday + timedelta(days=6)


def weekly_minutes_of(para):
    """Sum of weekly_minutes over ACTIVE assignments plus coverage_minutes of
    ACCEPTED backfills whose absence_date falls in the current ISO week."""
    total = 0
    for a in db.STORE["assignments"].values():
        if a["para_id"] == para["id"] and a["status"] == "ACTIVE":
            total += a["weekly_minutes"]
    monday, sunday = current_week_bounds()
    for b in db.STORE["backfills"].values():
        if b["substitute_para_id"] != para["id"] or b["status"] != "ACCEPTED":
            continue
        ab = db.STORE["absences"].get(b["absence_id"])
        if ab is None:
            continue
        d = parse_date(ab["absence_date"])
        if d is not None and monday <= d <= sunday:
            total += b["coverage_minutes"]
    return total


def benefit_eligible(para, plan):
    return weekly_minutes_of(para) >= plan["benefit_threshold_minutes"]


def committed_cost(plan):
    """Sum of projected_weekly_cost_cents over PROPOSED/QUALIFICATION_VERIFIED/
    ACTIVE assignments (SUSPENDED released its share)."""
    total = 0
    for a in db.STORE["assignments"].values():
        if a["plan_id"] == plan["id"] and a["status"] in (
                "PROPOSED", "QUALIFICATION_VERIFIED", "ACTIVE"):
            total += a["projected_weekly_cost_cents"]
    return total


def cost_balance(plan):
    return (plan["total_budget_cents"]
            - committed_cost(plan)
            - plan["settled_cost_cents"])


def coverage_posture(cp):
    if cp["status"] in ("LOCKED", "RECONCILED"):
        return "FROZEN"
    for ab in db.STORE["absences"].values():
        if ab["coverage_plan_id"] == cp["id"] and ab["status"] in NON_TERMINAL_ABSENCE:
            return "GAPS_OPEN"
    return "OPEN"


# ---------------------------------------------------------------------------
# Serializers (public field projections; internal _-prefixed keys excluded)
# ---------------------------------------------------------------------------

def ser_plan(p):
    return {
        "id": p["id"], "plan_name": p["plan_name"], "school_year": p["school_year"],
        "total_budget_cents": p["total_budget_cents"],
        "benefit_threshold_minutes": p["benefit_threshold_minutes"],
        "benefit_surcharge_pct": p["benefit_surcharge_pct"],
        "travel_buffer_minutes": p["travel_buffer_minutes"],
        "committed_cost_cents": committed_cost(p),
        "settled_cost_cents": p["settled_cost_cents"],
        "cost_balance_cents": cost_balance(p),
        "status": p["status"],
        "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_building(b):
    return {
        "id": b["id"], "plan_id": b["plan_id"], "name": b["name"],
        "building_code": b["building_code"], "hardship_factor": b["hardship_factor"],
        "created_at": b["created_at"], "updated_at": b["updated_at"],
        "version": b["version"],
    }


def ser_student(s):
    return {
        "id": s["id"], "plan_id": s["plan_id"], "building_id": s["building_id"],
        "student_ref": s["student_ref"], "iep_service_level": s["iep_service_level"],
        "iep_minutes_per_week": s["iep_minutes_per_week"],
        "required_qualification": s["required_qualification"], "status": s["status"],
        "created_at": s["created_at"], "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_para(p):
    plan = db.STORE["plans"].get(p["plan_id"])
    weekly = weekly_minutes_of(p)
    return {
        "id": p["id"], "plan_id": p["plan_id"],
        "home_building_id": p["home_building_id"], "full_name": p["full_name"],
        "email": p["email"], "base_hourly_wage_cents": p["base_hourly_wage_cents"],
        "contracted_max_weekly_minutes": p["contracted_max_weekly_minutes"],
        "hire_date": p["hire_date"], "qualifications": p["qualifications"],
        "weekly_scheduled_minutes": weekly,
        "benefit_eligible": (weekly >= plan["benefit_threshold_minutes"]) if plan else False,
        "confirmed_benefit_eligible": p["confirmed_benefit_eligible"],
        "benefit_variance_cents": p["benefit_variance_cents"],
        "status": p["status"],
        "created_at": p["created_at"], "updated_at": p["updated_at"],
        "version": p["version"],
    }


def ser_sco(o):
    return {
        "id": o["id"], "plan_id": o["plan_id"], "student_id": o["student_id"],
        "change_type": o["change_type"],
        "new_minutes_per_week": o["new_minutes_per_week"],
        "new_required_qualification": o["new_required_qualification"],
        "new_building_id": o["new_building_id"], "reason": o["reason"],
        "status": o["status"],
        "created_at": o["created_at"], "updated_at": o["updated_at"],
        "version": o["version"],
    }


def ser_assignment(a):
    return {
        "id": a["id"], "plan_id": a["plan_id"], "student_id": a["student_id"],
        "para_id": a["para_id"], "building_id": a["building_id"],
        "start_date": a["start_date"], "end_date": a["end_date"],
        "days_of_week": a["days_of_week"],
        "daily_start_minute": a["daily_start_minute"],
        "daily_end_minute": a["daily_end_minute"],
        "service_level_snapshot": a["service_level_snapshot"],
        "required_qualification_snapshot": a["required_qualification_snapshot"],
        "base_wage_snapshot_cents": a["base_wage_snapshot_cents"],
        "daily_cost_cents": a["daily_cost_cents"],
        "projected_weekly_cost_cents": a["projected_weekly_cost_cents"],
        "weekly_minutes": a["weekly_minutes"],
        "end_reason": a["end_reason"], "status": a["status"],
        "funding_status": a["funding_status"],
        "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_coverage_plan(c):
    return {
        "id": c["id"], "plan_id": c["plan_id"], "building_id": c["building_id"],
        "coverage_date": c["coverage_date"], "status": c["status"],
        "coverage_posture": coverage_posture(c),
        "created_at": c["created_at"], "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_absence(a):
    return {
        "id": a["id"], "plan_id": a["plan_id"], "assignment_id": a["assignment_id"],
        "coverage_plan_id": a["coverage_plan_id"], "absence_date": a["absence_date"],
        "absence_minutes": a["absence_minutes"], "reason": a["reason"],
        "reported_by_role": a["reported_by_role"],
        "declined_para_ids": a["declined_para_ids"], "status": a["status"],
        "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_backfill(b):
    return {
        "id": b["id"], "absence_id": b["absence_id"], "plan_id": b["plan_id"],
        "substitute_para_id": b["substitute_para_id"],
        "coverage_minutes": b["coverage_minutes"], "status": b["status"],
        "created_at": b["created_at"], "updated_at": b["updated_at"],
        "version": b["version"],
    }


def ser_timesheet(t):
    return {
        "id": t["id"], "plan_id": t["plan_id"], "para_id": t["para_id"],
        "assignment_id": t["assignment_id"], "work_date": t["work_date"],
        "start_minute": t["start_minute"], "end_minute": t["end_minute"],
        "minutes_worked": t["minutes_worked"], "status": t["status"],
        "created_at": t["created_at"], "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_evaluation(e):
    return {
        "id": e["id"], "plan_id": e["plan_id"], "para_id": e["para_id"],
        "period_start": e["period_start"], "period_end": e["period_end"],
        "professionalism_score": e["professionalism_score"],
        "instructional_support_score": e["instructional_support_score"],
        "comments": e["comments"], "created_by_user_id": e["created_by_user_id"],
        "countersigned_by_user_id": e["countersigned_by_user_id"],
        "resolution_note": e["resolution_note"], "status": e["status"],
        "created_at": e["created_at"], "updated_at": e["updated_at"],
        "version": e["version"],
    }


def ser_formula(f):
    return {
        "id": f["id"], "plan_id": f["plan_id"], "version_no": f["version_no"],
        "base_grant_cents": f["base_grant_cents"],
        "per_minute_rate_cents": f["per_minute_rate_cents"],
        "weight_one_to_one": f["weight_one_to_one"],
        "weight_shared_support": f["weight_shared_support"],
        "weight_transitional": f["weight_transitional"],
        "period_weeks": f["period_weeks"], "status": f["status"],
        "created_at": f["created_at"], "updated_at": f["updated_at"],
        "version": f["version"],
    }


def ser_allocation(a):
    return {
        "id": a["id"], "plan_id": a["plan_id"], "building_id": a["building_id"],
        "formula_id": a["formula_id"], "period_label": a["period_label"],
        "provisional_amount_cents": a["provisional_amount_cents"],
        "final_amount_cents": a["final_amount_cents"],
        "variance_cents": a["variance_cents"], "status": a["status"],
        "created_at": a["created_at"], "updated_at": a["updated_at"],
        "version": a["version"],
    }


# ---------------------------------------------------------------------------
# Qualification currency (PRD §3.3)
# ---------------------------------------------------------------------------

def qual_current(para, qual, on_date):
    """True when para holds `qual` completed on/before on_date, unexpired
    (expires_on null or strictly after on_date) and not revoked. NONE always holds."""
    if qual == "NONE":
        return True
    for q in para["qualifications"]:
        if q["qualification"] != qual or q["revoked"]:
            continue
        c = parse_date(q["completed_on"])
        e = parse_date(q["expires_on"]) if q["expires_on"] else None
        if c is not None and c <= on_date and (e is None or e > on_date):
            return True
    return False


# ---------------------------------------------------------------------------
# Assignment costing (calculations.assignment_daily_cost — pinned order)
# ---------------------------------------------------------------------------

def base_effective_rate(a):
    """Effective hourly rate BEFORE benefit surcharge, in cents (Decimal)."""
    return dec(
        a["base_wage_snapshot_cents"]
        + QUAL_DIFFERENTIAL[a["required_qualification_snapshot"]]
        + (SERVICE_STIPEND_ONE_TO_ONE if a["service_level_snapshot"] == "ONE_TO_ONE" else 0)
    )


def cost_assignment(a, para, plan):
    """Recompute daily/weekly cost for a NON-activated assignment.

    Pinned evaluation order: projected minutes (current weekly + self) decide
    eligibility; surcharge applies when eligible; per-day cost rounded half-up
    FIRST, then multiplied by the number of service days."""
    projected_minutes = weekly_minutes_of(para) + a["weekly_minutes"]
    eligible = projected_minutes >= plan["benefit_threshold_minutes"]
    rate = base_effective_rate(a)
    if eligible:
        rate = rate * (dec(1) + dec(plan["benefit_surcharge_pct"]))
    daily = rhu(dec(a["daily_end_minute"] - a["daily_start_minute"]) / dec(60) * rate)
    a["daily_cost_cents"] = daily
    a["projected_weekly_cost_cents"] = daily * len(a["days_of_week"])
    a["_cost_surcharged"] = eligible


def locked_hourly_rate(a, plan):
    """Effective hourly rate locked into the assignment's cost (Decimal)."""
    rate = base_effective_rate(a)
    if a.get("_cost_surcharged"):
        rate = rate * (dec(1) + dec(plan["benefit_surcharge_pct"]))
    return rate


def refresh_benefit_and_recost(para, plan):
    """Flip detection on the provisional benefit flag; a flip re-costs the
    para's PROPOSED/QUALIFICATION_VERIFIED assignments (PRD §3.4)."""
    flag = benefit_eligible(para, plan)
    if flag != para.get("_benefit_flag", False):
        para["_benefit_flag"] = flag
        for a in db.STORE["assignments"].values():
            if a["para_id"] == para["id"] and a["status"] in (
                    "PROPOSED", "QUALIFICATION_VERIFIED"):
                cost_assignment(a, para, plan)
                touch(a)


def bubble_up_refund(plan):
    """After every committed-cost release: reconsider the plan's UNFUNDED
    assignments, earliest-created first; re-fund any that fit again (PRD §3.5)."""
    remaining_base = plan["total_budget_cents"] - plan["settled_cost_cents"]
    cands = [a for a in db.STORE["assignments"].values()
             if a["plan_id"] == plan["id"] and a["funding_status"] == "UNFUNDED"]
    cands.sort(key=lambda a: (a["created_at"], a["_seq"]))
    for a in cands:
        if a["status"] in ("PROPOSED", "QUALIFICATION_VERIFIED"):
            # Its projected cost is already inside committed_cost.
            fits = committed_cost(plan) <= remaining_base
        elif a["status"] == "SUSPENDED":
            # Its share was released at suspension; fits if it slots back in.
            fits = (committed_cost(plan) + a["projected_weekly_cost_cents"]
                    <= remaining_base)
        else:
            continue
        if fits:
            a["funding_status"] = "PROVISIONALLY_FUNDED"
            touch(a)


# ---------------------------------------------------------------------------
# Schedule overlap (calculations.para_schedule_overlap): half-open intervals,
# same-building adjacency allowed, cross-building travel buffer on both sides.
# ---------------------------------------------------------------------------

def windows_conflict(s1, e1, b1, s2, e2, b2, buffer_minutes):
    if b1 == b2:
        return s1 < e2 and s2 < e1
    return s1 < e2 + buffer_minutes and s2 < e1 + buffer_minutes


def para_has_conflict(para, plan, days_of_week, s, e, building_id, exclude_id=None):
    """Any ACTIVE assignment of the para conflicting with the candidate window."""
    for o in db.STORE["assignments"].values():
        if (o["para_id"] != para["id"] or o["status"] != "ACTIVE"
                or o["id"] == exclude_id):
            continue
        if not set(days_of_week) & set(o["days_of_week"]):
            continue
        if windows_conflict(s, e, building_id,
                            o["daily_start_minute"], o["daily_end_minute"],
                            o["building_id"], plan["travel_buffer_minutes"]):
            return True
    return False


def timesheet_overlap(para_id, work_date, s, e, exclude_id=None):
    """Closed-interval double-log check vs SUBMITTED/APPROVED entries for the
    same para + work_date; touching endpoints count as conflict (PRD §3.7)."""
    for t in db.STORE["timesheets"].values():
        if t["para_id"] != para_id or t["work_date"] != work_date:
            continue
        if t["id"] == exclude_id:
            continue
        if t["status"] not in ("SUBMITTED", "APPROVED"):
            continue
        if s <= t["end_minute"] and t["start_minute"] <= e:
            return True
    return False


# ---------------------------------------------------------------------------
# Assignment lifecycle cascades
# ---------------------------------------------------------------------------

def suspend_assignment(a, para, plan):
    """ACTIVE -> SUSPENDED: release weekly minutes + committed share;
    funding_status stays FUNDED."""
    a["status"] = "SUSPENDED"
    touch(a)
    refresh_benefit_and_recost(para, plan)
    bubble_up_refund(plan)


def end_assignment(a, para, plan, end_reason):
    """Any non-terminal state -> ENDED with the per-state release cascade;
    funding_status -> SETTLED (PRD §3.5)."""
    a["status"] = "ENDED"
    a["end_reason"] = end_reason
    a["funding_status"] = "SETTLED"
    touch(a)
    refresh_benefit_and_recost(para, plan)
    bubble_up_refund(plan)


def end_assignments_cascade(assignments, plan, end_reason):
    """End a set of assignments (service-change / separation cascade),
    earliest-created first for determinism."""
    ordered = sorted(assignments, key=lambda a: (a["created_at"], a["_seq"]))
    for a in ordered:
        para = db.STORE["paras"].get(a["para_id"])
        if para is not None:
            end_assignment(a, para, plan, end_reason)


def find_coverage_plan_for(building_id, date_str):
    for c in db.STORE["coverage_plans"].values():
        if c["building_id"] == building_id and c["coverage_date"] == date_str:
            return c
    return None


def maybe_auto_absence(a, plan, role_label):
    """Auto-create a REPORTED absence when a suspended assignment's current
    weekday is scheduled and a PUBLISHED coverage plan covers (building, today)."""
    today = db.now().date()
    if WEEKDAYS[today.weekday()] not in a["days_of_week"]:
        return
    cp = find_coverage_plan_for(a["building_id"], today.isoformat())
    if cp is None or cp["status"] != "PUBLISHED":
        return
    ab = {
        "plan_id": a["plan_id"],
        "assignment_id": a["id"],
        "coverage_plan_id": cp["id"],
        "absence_date": today.isoformat(),
        "absence_minutes": a["daily_end_minute"] - a["daily_start_minute"],
        "reason": "system: required qualification no longer current",
        "reported_by_role": role_label,
        "declined_para_ids": [],
        "status": "REPORTED",
    }
    stamp_new(ab)
    db.STORE["absences"][ab["id"]] = ab


def lazy_expiry_sweep():
    """Lazy qualification-expiry cascade (PRD §2.4/§3.3): ACTIVE assignments
    whose required qualification is no longer current at the logical date are
    suspended, with the auto-absence side effect."""
    today = db.now().date()
    for a in list(db.STORE["assignments"].values()):
        if a["status"] != "ACTIVE" or a["required_qualification_snapshot"] == "NONE":
            continue
        para = db.STORE["paras"].get(a["para_id"])
        plan = db.STORE["plans"].get(a["plan_id"])
        if para is None or plan is None:
            continue
        if plan["status"] == "CLOSED":
            continue
        if not qual_current(para, a["required_qualification_snapshot"], today):
            suspend_assignment(a, para, plan)
            maybe_auto_absence(a, plan, "system")


# ---------------------------------------------------------------------------
# Backfill selector (calculations.backfill_selector)
# ---------------------------------------------------------------------------

def run_backfill_selector(absence, plan):
    a = db.STORE["assignments"][absence["assignment_id"]]
    d = parse_date(absence["absence_date"])
    weekday = WEEKDAYS[d.weekday()]
    s, e = a["daily_start_minute"], a["daily_end_minute"]
    pool = []
    for p in db.STORE["paras"].values():
        if p["plan_id"] != plan["id"]:
            continue
        if p["status"] != "ACTIVE":
            continue
        if p["id"] == a["para_id"]:
            continue
        if p["id"] in absence["declined_para_ids"]:
            continue
        if not qual_current(p, a["required_qualification_snapshot"], d):
            continue
        if para_has_conflict(p, plan, [weekday], s, e, a["building_id"]):
            continue
        if (weekly_minutes_of(p) + absence["absence_minutes"]
                > p["contracted_max_weekly_minutes"]):
            continue
        pool.append(p)
    pool.sort(key=lambda p: (
        weekly_minutes_of(p),
        p["base_hourly_wage_cents"],
        p["hire_date"],
        p["created_at"],
        p["_seq"],
    ))
    return pool[0] if pool else None


# ---------------------------------------------------------------------------
# Building allocation variants (calculations.building_allocation)
# ---------------------------------------------------------------------------

def _weight(formula, service_level):
    return {
        "ONE_TO_ONE": formula["weight_one_to_one"],
        "SHARED_SUPPORT": formula["weight_shared_support"],
        "TRANSITIONAL": formula["weight_transitional"],
    }[service_level]


def provisional_building_amount(formula, building, plan):
    """Forward-looking variant: entitlement minutes x weights x rate x weeks,
    rounded half-up FIRST, then hardship factor applied and rounded once more."""
    service_sum = dec(0)
    for s in db.STORE["students"].values():
        if s["building_id"] != building["id"] or s["plan_id"] != plan["id"]:
            continue
        if s["status"] not in ("REGISTERED", "ACTIVE_IEP", "SERVICE_CHANGE_PENDING"):
            continue
        service_sum += dec(_weight(formula, s["iep_service_level"])) * dec(
            s["iep_minutes_per_week"])
    raw = (dec(formula["base_grant_cents"])
           + service_sum * dec(formula["per_minute_rate_cents"])
           * dec(formula["period_weeks"]))
    rounded = dec(rhu(raw))
    return rhu(rounded * dec(building["hardship_factor"]))


def final_building_amount(formula, building, plan):
    """Chronological variant at plan close: APPROVED timesheet minutes mapped
    via assignment.student_id to students whose CURRENT building is this one,
    weighted by the student's CURRENT service level; period_weeks NOT applied."""
    weighted_minutes = dec(0)
    for t in db.STORE["timesheets"].values():
        if t["plan_id"] != plan["id"] or t["status"] != "APPROVED":
            continue
        a = db.STORE["assignments"].get(t["assignment_id"])
        if a is None:
            continue
        stu = db.STORE["students"].get(a["student_id"])
        if stu is None or stu["building_id"] != building["id"]:
            continue
        weighted_minutes += dec(t["minutes_worked"]) * dec(
            _weight(formula, stu["iep_service_level"]))
    raw = (dec(formula["base_grant_cents"])
           + weighted_minutes * dec(formula["per_minute_rate_cents"]))
    rounded = dec(rhu(raw))
    return rhu(rounded * dec(building["hardship_factor"]))


# ---------------------------------------------------------------------------
# Plan close (PRD §3.9)
# ---------------------------------------------------------------------------

def close_plan(plan):
    today = db.now().date()
    threshold = plan["benefit_threshold_minutes"]

    # --- Confirmed benefit eligibility + clawback variance per para ---
    for p in db.STORE["paras"].values():
        if p["plan_id"] != plan["id"]:
            continue
        approved = [t for t in db.STORE["timesheets"].values()
                    if t["plan_id"] == plan["id"] and t["para_id"] == p["id"]
                    and t["status"] == "APPROVED"]
        starts = [parse_date(a["start_date"])
                  for a in db.STORE["assignments"].values()
                  if a["plan_id"] == plan["id"] and a["para_id"] == p["id"]]
        starts = [d for d in starts if d is not None]
        confirmed = False
        variance = 0
        if starts:
            w = week_monday(min(starts))
            last = week_monday(today)
            approved_dates = [parse_date(t["work_date"]) for t in approved]
            approved_dates = [d for d in approved_dates if d is not None]
            if approved_dates and week_monday(max(approved_dates)) > last:
                last = week_monday(max(approved_dates))
            while w <= last:
                w_end = w + timedelta(days=6)
                approved_minutes = sum(
                    t["minutes_worked"] for t in approved
                    if (parse_date(t["work_date"]) is not None
                        and w <= parse_date(t["work_date"]) <= w_end))
                if approved_minutes >= threshold:
                    confirmed = True
                else:
                    # Clawback: each assignment ACTIVE during this week
                    # (approximated: ever-activated + date-range overlap)
                    # contributes its surcharge component only.
                    for a in db.STORE["assignments"].values():
                        if (a["plan_id"] != plan["id"] or a["para_id"] != p["id"]
                                or not a.get("_cost_locked")):
                            continue
                        a_start = parse_date(a["start_date"])
                        a_end = parse_date(a["end_date"])
                        if a_start is None or a_end is None:
                            continue
                        if a_start <= w_end and a_end >= w:
                            daily0 = rhu(
                                dec(a["daily_end_minute"] - a["daily_start_minute"])
                                / dec(60) * base_effective_rate(a))
                            weekly0 = daily0 * len(a["days_of_week"])
                            variance += a["projected_weekly_cost_cents"] - weekly0
                w += timedelta(days=7)
        p["confirmed_benefit_eligible"] = confirmed
        p["benefit_variance_cents"] = variance
        touch(p)

    # --- Final allocation variant per FundingAllocation row ---
    for al in db.STORE["allocations"].values():
        if al["plan_id"] != plan["id"]:
            continue
        formula = db.STORE["formulas"].get(al["formula_id"])
        building = db.STORE["buildings"].get(al["building_id"])
        if formula is None or building is None:
            continue
        final = final_building_amount(formula, building, plan)
        al["final_amount_cents"] = final
        al["variance_cents"] = final - al["provisional_amount_cents"]
        al["status"] = "FINALIZED"
        touch(al)

    # --- Settled labor cost over APPROVED timesheets (round per entry) ---
    settled = 0
    for t in db.STORE["timesheets"].values():
        if t["plan_id"] != plan["id"] or t["status"] != "APPROVED":
            continue
        a = db.STORE["assignments"].get(t["assignment_id"])
        if a is None:
            continue
        rate = locked_hourly_rate(a, plan)
        settled += rhu(dec(t["minutes_worked"]) / dec(60) * rate)
    plan["settled_cost_cents"] = settled

    # --- End remaining ACTIVE/SUSPENDED assignments (PLAN_CLOSED) ---
    for a in db.STORE["assignments"].values():
        if a["plan_id"] == plan["id"] and a["status"] in ("ACTIVE", "SUSPENDED"):
            a["status"] = "ENDED"
            a["end_reason"] = "PLAN_CLOSED"
            a["funding_status"] = "SETTLED"
            touch(a)

    plan["status"] = "CLOSED"
    touch(plan)
