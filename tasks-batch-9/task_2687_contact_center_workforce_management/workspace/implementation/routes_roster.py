"""Agents, shift templates and the hiring pipeline (PRD 3.4, 3.5)."""
from datetime import timedelta

from flask import Blueprint

import calc
from cascade import (
    require_not_frozen, set_fields, recompute_enrolled_agent_count,
    recompute_headcount_active, recompute_pipeline_fte, shifts_of_agent,
)
from core import (
    D, bad, body, created, date_to_dt, fail, get, iso_date, new_row, now_dt, ok,
    public, q2, q4, rows, require_auth, v_array, v_date, v_enum, v_id, v_int, v_num,
    v_skill, v_skill_array, v_string,
)
from listing import std_list, array_contains_filter

bp = Blueprint("roster", __name__)

AGENT_READERS = ["CapacityPlanner", "WorkforceAnalyst", "SchedulingManager",
                 "IntradayController", "TeamCoach", "Agent"]
CLASS_READERS = ["CapacityPlanner", "WorkforceAnalyst", "SchedulingManager", "TeamCoach"]
TIME_RE = r"^(?:[01]\d|2[0-3]):[0-5]\d$"


def cycles_holding_agent(agent_id):
    out = {}
    for shift in shifts_of_agent(agent_id):
        if shift["publication_status"] in ("DRAFT", "PUBLISHED"):
            cycle = get("planning_cycles", shift["planning_cycle_id"])
            out[cycle["id"]] = cycle
    return out


def cycles_of_agent_classes(agent):
    out = {}
    if agent["hiring_class_id"] is not None:
        cls = DB_class(agent["hiring_class_id"])
        if cls is not None:
            cycle = get("planning_cycles", cls["planning_cycle_id"])
            out[cycle["id"]] = cycle
    return out


def DB_class(class_id):
    from core import maybe
    return maybe("hiring_classes", class_id)


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------
@bp.post("/agents")
def create_agent():
    require_auth(["SchedulingManager"])
    b = body()
    agreement_id = v_id(b, "labor_agreement_id")
    employee_code = v_string(b, "employee_code", maxlen=40)
    full_name = v_string(b, "full_name", maxlen=120)
    skills = v_skill_array(b, "skills")
    seniority = v_int(b, "seniority_rank", minimum=1)
    weekly_hours = v_num(b, "weekly_contracted_hours", exclusive_min=0)
    rate = v_int(b, "hourly_rate_cents", minimum=1)
    if any(r["employee_code"] == employee_code for r in rows("agents")):
        bad("employee_code", "must be unique across all agents")
    agreement = get("labor_agreements", agreement_id)
    row = new_row("agents", {
        "labor_agreement_id": agreement["id"],
        "hiring_class_id": None,
        "employee_code": employee_code,
        "full_name": full_name,
        "skills": skills,
        "seniority_rank": seniority,
        "weekly_contracted_hours": weekly_hours,
        "hourly_rate_cents": rate,
        "status": "ACTIVE",
        "scheduled_hours_committed": q2(0),
        "adherence_pct": q4(1),
        "coaching_flag_count": 0,
        "coaching_status": "NONE",
    })
    recompute_enrolled_agent_count(agreement)
    return created(public(row))


@bp.get("/agents/<agent_id>")
def read_agent(agent_id):
    require_auth(AGENT_READERS)
    return ok(public(get("agents", agent_id)))


@bp.get("/agents")
def list_agents():
    require_auth(AGENT_READERS)
    return std_list(
        "agents",
        [("labor_agreement_id", "labor_agreement_id"),
         ("hiring_class_id", "hiring_class_id"),
         ("status", "status")],
        extra=array_contains_filter("skill_code", "skills"),
    )


@bp.patch("/agents/<agent_id>")
def update_agent(agent_id):
    require_auth(["SchedulingManager"])
    b = body()
    target = v_enum(b, "target_status", ("ACTIVE", "LEAVE", "TERMINATED"), required=False)
    skills = v_skill_array(b, "skills", required=False) if "skills" in b and b["skills"] is not None else None
    seniority = v_int(b, "seniority_rank", required=False, minimum=1)
    rate = v_int(b, "hourly_rate_cents", required=False, minimum=1)
    agent = get("agents", agent_id)
    current = agent["status"]
    updates = {}
    if skills is not None:
        updates["skills"] = skills
    if seniority is not None:
        updates["seniority_rank"] = seniority
    if rate is not None:
        updates["hourly_rate_cents"] = rate
    if target is not None:
        legal = {("ACTIVE", "LEAVE"), ("LEAVE", "ACTIVE"),
                 ("ACTIVE", "TERMINATED"), ("LEAVE", "TERMINATED")}
        if (current, target) not in legal:
            fail("ERR_INVALID_STATE", "%s is not reachable from %s" % (target, current))
        if target == "TERMINATED":
            if any(s["publication_status"] == "PUBLISHED" for s in shifts_of_agent(agent["id"])):
                fail("ERR_INVALID_STATE", "The agent still holds a published shift")
        updates["status"] = target
    set_fields(agent, updates)
    if target is not None:
        cycles = cycles_holding_agent(agent["id"])
        cycles.update(cycles_of_agent_classes(agent))
        if target == "TERMINATED":
            recompute_enrolled_agent_count(get("labor_agreements", agent["labor_agreement_id"]))
        for cycle in cycles.values():
            recompute_headcount_active(cycle)
    return ok(public(agent))


# ---------------------------------------------------------------------------
# Shift templates
# ---------------------------------------------------------------------------
@bp.post("/shift-templates")
def create_shift_template():
    require_auth(["SchedulingManager"])
    b = body()
    cycle_id = v_id(b, "planning_cycle_id")
    code = v_string(b, "code", maxlen=40)
    skill_code = v_skill(b, "skill_code")
    start_time = v_string(b, "start_time_local", pattern=TIME_RE)
    duration = v_int(b, "duration_minutes", minimum=60, maximum=720)
    days = v_array(b, "days_of_week", minlen=1)
    seen = set()
    for day in days:
        if isinstance(day, bool) or not isinstance(day, int) or day < 0 or day > 6:
            bad("days_of_week", "must contain distinct ISO weekday indexes between 0 and 6")
        if day in seen:
            bad("days_of_week", "must contain distinct ISO weekday indexes between 0 and 6")
        seen.add(day)
    slots_total = v_int(b, "slots_total", minimum=1)
    unpaid_break = v_int(b, "unpaid_break_minutes", required=False, minimum=0, default=30)
    if unpaid_break >= duration:
        bad("unpaid_break_minutes", "must be strictly less than duration_minutes")
    cycle = get("planning_cycles", cycle_id)
    for other in rows("shift_templates"):
        if other["planning_cycle_id"] == cycle["id"] and other["code"] == code:
            bad("code", "must be unique within the planning cycle")
    require_not_frozen(cycle)
    row = new_row("shift_templates", {
        "planning_cycle_id": cycle["id"],
        "code": code,
        "skill_code": skill_code,
        "start_time_local": start_time,
        "duration_minutes": duration,
        "unpaid_break_minutes": unpaid_break,
        "days_of_week": days,
        "slots_total": slots_total,
        "slots_awarded": 0,
    })
    return created(public(row))


@bp.get("/shift-templates/<shift_template_id>")
def read_shift_template(shift_template_id):
    require_auth(AGENT_READERS)
    return ok(public(get("shift_templates", shift_template_id)))


@bp.get("/shift-templates")
def list_shift_templates():
    require_auth(AGENT_READERS)
    return std_list("shift_templates", [
        ("planning_cycle_id", "planning_cycle_id"),
        ("skill_code", "skill_code"),
    ])


# ---------------------------------------------------------------------------
# Hiring classes
# ---------------------------------------------------------------------------
def apply_ramp(cls, cycle):
    expected, nesting_from, productive_from, fte = calc.hiring_class_ramp(cls, cycle)
    set_fields(cls, {
        "expected_graduates": expected,
        "nesting_from_date": iso_date(nesting_from),
        "productive_from_date": iso_date(productive_from),
        "effective_fte_at_horizon_end": fte,
    })
    cls["_nesting_from"] = nesting_from
    cls["_productive_from"] = productive_from
    return expected


@bp.post("/hiring-classes")
def create_hiring_class():
    require_auth(["CapacityPlanner"])
    b = body()
    cycle_id = v_id(b, "planning_cycle_id")
    agreement_id = v_id(b, "labor_agreement_id")
    cohort_name = v_string(b, "cohort_name", maxlen=80)
    skill_code = v_skill(b, "skill_code")
    start_date = v_date(b, "start_date")
    seats = v_int(b, "seats", minimum=1, maximum=200)
    training_weeks = v_int(b, "training_weeks", minimum=1, maximum=12)
    nesting_weeks = v_int(b, "nesting_weeks", minimum=0, maximum=8)
    attrition = v_num(b, "expected_attrition_pct", minimum=0)
    if attrition >= D(1):
        bad("expected_attrition_pct", "must be strictly less than 1")
    grad_rate = v_int(b, "graduate_hourly_rate_cents", minimum=1)
    grad_hours = v_num(b, "graduate_weekly_hours", exclusive_min=0)
    if any(r["cohort_name"] == cohort_name for r in rows("hiring_classes")):
        bad("cohort_name", "must be unique across all hiring classes")
    cycle = get("planning_cycles", cycle_id)
    agreement = get("labor_agreements", agreement_id)
    require_not_frozen(cycle)
    row = new_row("hiring_classes", {
        "planning_cycle_id": cycle["id"],
        "labor_agreement_id": agreement["id"],
        "cohort_name": cohort_name,
        "skill_code": skill_code,
        "start_date": iso_date(start_date),
        "seats": seats,
        "training_weeks": training_weeks,
        "nesting_weeks": nesting_weeks,
        "expected_attrition_pct": q4(attrition),
        "graduate_hourly_rate_cents": grad_rate,
        "graduate_weekly_hours": grad_hours,
        "expected_graduates": 0,
        "nesting_from_date": None,
        "productive_from_date": None,
        "effective_fte_at_horizon_end": q2(0),
        "graduated_agent_count": 0,
        "status": "PLANNED",
        "_start_date": start_date,
    })
    apply_ramp(row, cycle)
    return created(public(row))


@bp.get("/hiring-classes/<hiring_class_id>")
def read_hiring_class(hiring_class_id):
    require_auth(CLASS_READERS)
    return ok(public(get("hiring_classes", hiring_class_id)))


@bp.get("/hiring-classes")
def list_hiring_classes():
    require_auth(CLASS_READERS)
    return std_list("hiring_classes", [
        ("planning_cycle_id", "planning_cycle_id"),
        ("labor_agreement_id", "labor_agreement_id"),
        ("status", "status"),
    ])


@bp.post("/hiring-classes/<hiring_class_id>/status")
def drive_hiring_class(hiring_class_id):
    require_auth(["CapacityPlanner"])
    b = body()
    target = v_enum(b, "target_status",
                    ("PLANNED", "CHARTERED", "IN_TRAINING", "GRADUATED", "CANCELLED"))
    cls = get("hiring_classes", hiring_class_id)
    cycle = get("planning_cycles", cls["planning_cycle_id"])
    require_not_frozen(cycle)
    current = cls["status"]
    if current == "PLANNED" and target == "CHARTERED":
        set_fields(cls, {"status": "CHARTERED"})
        apply_ramp(cls, cycle)
        recompute_pipeline_fte(cycle)
    elif current == "CHARTERED" and target == "IN_TRAINING":
        if now_dt() < date_to_dt(cls["_start_date"]):
            fail("ERR_INVALID_STATE", "The logical clock has not reached start_date")
        set_fields(cls, {"status": "IN_TRAINING"})
        apply_ramp(cls, cycle)
        recompute_pipeline_fte(cycle)
    elif target == "CANCELLED" and current in ("PLANNED", "CHARTERED", "IN_TRAINING"):
        set_fields(cls, {"status": "CANCELLED"})
        if current in ("CHARTERED", "IN_TRAINING"):
            recompute_pipeline_fte(cycle)
    else:
        fail("ERR_INVALID_STATE", "%s is not reachable from %s" % (target, current))
    return ok(public(cls))


@bp.post("/hiring-classes/<hiring_class_id>/graduate")
def graduate_hiring_class(hiring_class_id):
    require_auth(["CapacityPlanner"])
    cls = get("hiring_classes", hiring_class_id)
    cycle = get("planning_cycles", cls["planning_cycle_id"])
    require_not_frozen(cycle)
    if cls["status"] != "IN_TRAINING":
        fail("ERR_INVALID_STATE", "Graduation is only reachable from IN_TRAINING")
    if now_dt() < date_to_dt(cls["_nesting_from"]):
        fail("ERR_INVALID_STATE", "The logical clock has not reached nesting_from_date")
    agreement = get("labor_agreements", cls["labor_agreement_id"])
    expected = int(cls["expected_graduates"])
    set_fields(cls, {"status": "GRADUATED"})
    for index in range(1, expected + 1):
        code = "%s-%03d" % (cls["cohort_name"], index)
        new_row("agents", {
            "labor_agreement_id": agreement["id"],
            "hiring_class_id": cls["id"],
            "employee_code": code,
            "full_name": code,
            "skills": [cls["skill_code"]],
            "seniority_rank": 1,
            "weekly_contracted_hours": cls["graduate_weekly_hours"],
            "hourly_rate_cents": int(cls["graduate_hourly_rate_cents"]),
            "status": "ACTIVE",
            "scheduled_hours_committed": q2(0),
            "adherence_pct": q4(1),
            "coaching_flag_count": 0,
            "coaching_status": "NONE",
        })
    set_fields(cls, {"graduated_agent_count": expected})
    recompute_enrolled_agent_count(agreement)
    recompute_headcount_active(cycle)
    recompute_pipeline_fte(cycle)
    return ok(public(cls))
