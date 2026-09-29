"""Schedule shifts (two parallel state axes) and adherence exceptions (PRD 3.6, 3.8)."""
from flask import Blueprint, g

import calc
from cascade import (
    actions_of_shift, agreement_of, check_consecutive_days, check_min_rest,
    check_overlap, check_weekly_hours, intervals_covered_by, mint_shift,
    projected_weekly_hours, recompute_agent_adherence, recompute_agent_hours,
    recompute_coverage_for_intervals, recompute_headcount_active,
    recompute_total_scheduled_hours, require_not_frozen, set_fields, template_of,
)
from core import (
    D, bad, body, created, fail, get, new_row, ok, public, q4, rows, require_auth,
    v_date, v_enum, v_id, v_int, v_string,
)
from listing import std_list

bp = Blueprint("shifts", __name__)

SHIFT_READERS = ["CapacityPlanner", "WorkforceAnalyst", "SchedulingManager",
                 "IntradayController", "TeamCoach", "Agent"]
REASON_CODES = ("SYSTEM_OUTAGE", "APPROVED_MEETING", "COACHING_SESSION",
                "MEDICAL", "TRANSIT_DISRUPTION")
LOCKED_POSTURES = ("REQUIREMENTS_LOCKED", "SCHEDULE_PUBLISHED", "INTRADAY_ALERT")


# ---------------------------------------------------------------------------
# Schedule shifts
# ---------------------------------------------------------------------------
@bp.post("/schedule-shifts")
def create_schedule_shift():
    require_auth(["SchedulingManager"])
    b = body()
    cycle_id = v_id(b, "planning_cycle_id")
    agent_id = v_id(b, "agent_id")
    template_id = v_id(b, "shift_template_id")
    service_date = v_date(b, "service_date")
    cycle = get("planning_cycles", cycle_id)
    agent = get("agents", agent_id)
    template = get("shift_templates", template_id)
    require_not_frozen(cycle)
    if not (cycle["_horizon_start"] <= service_date <= cycle["_horizon_end"]):
        fail("ERR_INTERVAL_OUTSIDE_HORIZON",
             "The service date falls outside the cycle horizon")
    row = mint_shift(cycle, agent, template, service_date)
    return created(public(row))


@bp.get("/schedule-shifts/<schedule_shift_id>")
def read_schedule_shift(schedule_shift_id):
    require_auth(SHIFT_READERS)
    return ok(public(get("schedule_shifts", schedule_shift_id)))


@bp.get("/schedule-shifts")
def list_schedule_shifts():
    require_auth(SHIFT_READERS)
    return std_list("schedule_shifts", [
        ("planning_cycle_id", "planning_cycle_id"),
        ("agent_id", "agent_id"),
        ("shift_template_id", "shift_template_id"),
        ("service_date", "service_date"),
        ("publication_status", "publication_status"),
        ("adherence_status", "adherence_status"),
    ])


@bp.post("/schedule-shifts/<schedule_shift_id>/publication")
def drive_publication(schedule_shift_id):
    require_auth(["SchedulingManager"])
    b = body()
    target = v_enum(b, "target_publication_status", ("DRAFT", "PUBLISHED", "CANCELLED"))
    shift = get("schedule_shifts", schedule_shift_id)
    cycle = get("planning_cycles", shift["planning_cycle_id"])
    require_not_frozen(cycle)
    current = shift["publication_status"]
    agent = get("agents", shift["agent_id"])
    if current == "DRAFT" and target == "PUBLISHED":
        if cycle["posture"] not in LOCKED_POSTURES:
            fail("ERR_CYCLE_NOT_LOCKED",
                 "The cycle posture does not admit publishing a schedule")
        if agent["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE", "The agent's employment status is not ACTIVE")
        template = template_of(shift)
        agreement = agreement_of(agent)
        # Section 2.10 fixes the business-rule band order: the four labour-safety
        # checks run ahead of skill eligibility.
        check_min_rest(agent, agreement, shift)
        check_overlap(agent, shift)
        check_weekly_hours(
            agreement,
            projected_weekly_hours(agent["id"], shift, shift["paid_hours"], force_include=True),
        )
        check_consecutive_days(agent, agreement)
        if template["skill_code"] not in agent["skills"]:
            fail("ERR_SKILL_MISMATCH",
                 "The agent does not hold skill %s" % template["skill_code"])
        set_fields(shift, {"publication_status": "PUBLISHED"})
        recompute_agent_hours(agent)
        recompute_total_scheduled_hours(cycle)
        recompute_coverage_for_intervals(intervals_covered_by(shift))
        recompute_headcount_active(cycle)
    elif current == "PUBLISHED" and target == "CANCELLED":
        for act in actions_of_shift(shift["id"]):
            if act["status"] == "ACCEPTED":
                fail("ERR_INVALID_STATE",
                     "The shift carries an accepted intraday action")
        covered = intervals_covered_by(shift)
        set_fields(shift, {"publication_status": "CANCELLED"})
        recompute_agent_hours(agent)
        recompute_total_scheduled_hours(cycle)
        recompute_coverage_for_intervals(covered)
        recompute_headcount_active(cycle)
        recompute_agent_adherence(agent)
    elif current == "DRAFT" and target == "CANCELLED":
        set_fields(shift, {"publication_status": "CANCELLED"})
    else:
        fail("ERR_INVALID_STATE", "%s is not reachable from %s" % (target, current))
    return ok(public(shift))


ADHERENCE_EDGES = {
    ("PENDING", "ON_TRACK"),
    ("PENDING", "OUT_OF_ADHERENCE"),
    ("ON_TRACK", "OUT_OF_ADHERENCE"),
    ("OUT_OF_ADHERENCE", "ON_TRACK"),
    ("EXCUSED", "OUT_OF_ADHERENCE"),
}


@bp.post("/schedule-shifts/<schedule_shift_id>/adherence-observations")
def record_observation(schedule_shift_id):
    uid, _role = require_auth(["IntradayController"])
    b = body()
    seconds = v_int(b, "out_of_adherence_seconds", minimum=0)
    shift = get("schedule_shifts", schedule_shift_id)
    cycle = get("planning_cycles", shift["planning_cycle_id"])
    require_not_frozen(cycle)
    if shift["publication_status"] != "PUBLISHED":
        fail("ERR_SHIFT_NOT_PUBLISHED", "The shift is not published")
    pct = calc.adherence_score(shift["scheduled_seconds"], seconds, 0)
    target = "ON_TRACK" if pct >= calc.COACHING_ADHERENCE_THRESHOLD else "OUT_OF_ADHERENCE"
    current = shift["adherence_status"]
    if (current, target) not in ADHERENCE_EDGES:
        fail("ERR_INVALID_STATE", "%s is not reachable from %s" % (target, current))
    updates = {
        "out_of_adherence_seconds": seconds,
        "excused_seconds": 0,
        "adherence_pct": pct,
        "adherence_status": target,
    }
    if target == "OUT_OF_ADHERENCE":
        updates["flagged_by_user_id"] = uid
    set_fields(shift, updates)
    recompute_agent_adherence(get("agents", shift["agent_id"]))
    return ok(public(shift))


# ---------------------------------------------------------------------------
# Adherence exceptions
# ---------------------------------------------------------------------------
@bp.post("/adherence-exceptions")
def create_adherence_exception():
    require_auth(["Agent"])
    b = body()
    shift_id = v_id(b, "schedule_shift_id")
    agent_id = v_id(b, "agent_id")
    reason = v_enum(b, "reason_code", REASON_CODES)
    duration = v_int(b, "duration_seconds", minimum=1)
    narrative = v_string(b, "narrative", maxlen=500)
    shift = get("schedule_shifts", shift_id)
    agent = get("agents", agent_id)
    if agent["id"] != g.user_id or shift["agent_id"] != agent["id"]:
        fail("ERR_OWNERSHIP_VIOLATION",
             "An agent may only file an exception against their own shift")
    cycle = get("planning_cycles", shift["planning_cycle_id"])
    require_not_frozen(cycle)
    if shift["publication_status"] != "PUBLISHED":
        fail("ERR_SHIFT_NOT_PUBLISHED", "The shift is not published")
    if duration > int(shift["out_of_adherence_seconds"]):
        bad("duration_seconds",
            "may not exceed the shift's out_of_adherence_seconds")
    row = new_row("adherence_exceptions", {
        "schedule_shift_id": shift["id"],
        "agent_id": agent["id"],
        "reason_code": reason,
        "duration_seconds": duration,
        "narrative": narrative,
        "coach_note": None,
        "decided_by_user_id": None,
        "info_requested_count": 0,
        "status": "SUBMITTED",
    })
    return created(public(row))


@bp.get("/adherence-exceptions/<adherence_exception_id>")
def read_adherence_exception(adherence_exception_id):
    require_auth(SHIFT_READERS)
    return ok(public(get("adherence_exceptions", adherence_exception_id)))


@bp.get("/adherence-exceptions")
def list_adherence_exceptions():
    require_auth(SHIFT_READERS)
    return std_list("adherence_exceptions", [
        ("schedule_shift_id", "schedule_shift_id"),
        ("agent_id", "agent_id"),
        ("status", "status"),
    ])


@bp.post("/adherence-exceptions/<adherence_exception_id>/decision")
def decide_adherence_exception(adherence_exception_id):
    uid, _role = require_auth(["TeamCoach"])
    b = body()
    decision = v_enum(b, "decision", ("APPROVE", "REJECT", "REQUEST_INFO"))
    note = v_string(b, "coach_note", required=False, maxlen=500)
    exc = get("adherence_exceptions", adherence_exception_id)
    shift = get("schedule_shifts", exc["schedule_shift_id"])
    if shift["flagged_by_user_id"] is not None and uid == shift["flagged_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "A coach may not decide a case they themselves flagged")
    cycle = get("planning_cycles", shift["planning_cycle_id"])
    require_not_frozen(cycle)
    if exc["status"] != "SUBMITTED":
        fail("ERR_EXCEPTION_NOT_PENDING", "The exception is not awaiting decision")
    if decision == "APPROVE":
        if int(exc["duration_seconds"]) > int(shift["out_of_adherence_seconds"]):
            bad("duration_seconds",
                "may not exceed the shift's current out_of_adherence_seconds")
        if shift["adherence_status"] != "OUT_OF_ADHERENCE":
            fail("ERR_INVALID_STATE",
                 "EXCUSED is only reachable from OUT_OF_ADHERENCE")
        updates = {"status": "APPROVED", "decided_by_user_id": uid}
        if note is not None:
            updates["coach_note"] = note
        set_fields(exc, updates)
        excused = int(shift["excused_seconds"]) + int(exc["duration_seconds"])
        set_fields(shift, {
            "excused_seconds": excused,
            "adherence_status": "EXCUSED",
            "adherence_pct": calc.adherence_score(
                shift["scheduled_seconds"], shift["out_of_adherence_seconds"], excused
            ),
        })
        recompute_agent_adherence(get("agents", shift["agent_id"]))
    elif decision == "REJECT":
        updates = {"status": "REJECTED", "decided_by_user_id": uid}
        if note is not None:
            updates["coach_note"] = note
        set_fields(exc, updates)
    else:
        updates = {"status": "INFO_REQUESTED"}
        if note is not None:
            updates["coach_note"] = note
        set_fields(exc, updates)
    return ok(public(exc))


@bp.post("/adherence-exceptions/<adherence_exception_id>/resubmit")
def resubmit_adherence_exception(adherence_exception_id):
    require_auth(["Agent"])
    b = body()
    narrative = v_string(b, "narrative", maxlen=500)
    duration = v_int(b, "duration_seconds", minimum=1)
    exc = get("adherence_exceptions", adherence_exception_id)
    if exc["agent_id"] != g.user_id:
        fail("ERR_OWNERSHIP_VIOLATION",
             "An agent may only resubmit their own exception")
    shift = get("schedule_shifts", exc["schedule_shift_id"])
    cycle = get("planning_cycles", shift["planning_cycle_id"])
    require_not_frozen(cycle)
    if exc["status"] != "INFO_REQUESTED":
        fail("ERR_EXCEPTION_NOT_PENDING",
             "Only an exception sent back for information may be resubmitted")
    if duration > int(shift["out_of_adherence_seconds"]):
        bad("duration_seconds",
            "may not exceed the shift's out_of_adherence_seconds")
    set_fields(exc, {
        "narrative": narrative,
        "duration_seconds": duration,
        "status": "SUBMITTED",
        "info_requested_count": int(exc["info_requested_count"]) + 1,
    })
    return ok(public(exc))
