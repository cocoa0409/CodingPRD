"""Logical clock, planning cycles and labour agreements (PRD 2.5, 3.1)."""
from datetime import timedelta

from flask import Blueprint

import calc
from cascade import (
    require_not_frozen, set_fields, recompute_short_interval_count,
    recompute_interval_forecast, shifts_of_cycle,
)
from core import (
    ALL_OPERATORS, CLOCK, D, body, bad, created, fail, get, iso_date, now_iso, ok,
    public, q2, q4, rows, require_auth, v_date, v_datetime, v_enum, v_id, v_int,
    v_num, v_string, filter_arg,
)
from listing import std_list

bp = Blueprint("planning", __name__)

POSTURES = ("OPEN", "REQUIREMENTS_LOCKED", "SCHEDULE_PUBLISHED", "INTRADAY_ALERT", "FROZEN")
CYCLE_READERS = ["CapacityPlanner", "WorkforceAnalyst", "SchedulingManager",
                 "IntradayController", "TeamCoach", "SourcingManager", "Agent"]


# ---------------------------------------------------------------------------
# The logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    require_auth(ALL_OPERATORS)
    b = body()
    raw, parsed = v_datetime(b, "to_iso8601")
    previous = CLOCK["raw"]
    CLOCK["raw"] = raw
    CLOCK["dt"] = parsed
    return ok({"current_utc": raw, "previous_utc": previous})


# ---------------------------------------------------------------------------
# Planning cycles
# ---------------------------------------------------------------------------
@bp.post("/planning-cycles")
def create_planning_cycle():
    require_auth(["CapacityPlanner"])
    b = body()
    name = v_string(b, "name", maxlen=80)
    start = v_date(b, "horizon_start_date")
    end = v_date(b, "horizon_end_date")
    if start.weekday() != 0:
        bad("horizon_start_date", "must be a Monday")
    if end != start + timedelta(days=6):
        bad("horizon_end_date", "must be exactly six days after horizon_start_date")
    interval_minutes = v_int(b, "interval_minutes", required=False, default=30)
    if interval_minutes not in (15, 30, 60):
        bad("interval_minutes", "must be 15, 30 or 60")
    basis = v_enum(b, "requirement_basis", ("SERVICE_LEVEL", "OCCUPANCY", "MAX_OF_BOTH"),
                   required=False, default="MAX_OF_BOTH")
    ot_budget = v_int(b, "ot_budget_cents", required=False, minimum=0, default=1000000)
    threshold = v_int(b, "intraday_alert_short_threshold", required=False, minimum=1, default=3)
    row = new_cycle(name, start, end, interval_minutes, basis, ot_budget, threshold)
    return created(public(row))


def new_cycle(name, start, end, interval_minutes, basis, ot_budget, threshold):
    from core import new_row
    return new_row("planning_cycles", {
        "name": name,
        "horizon_start_date": iso_date(start),
        "horizon_end_date": iso_date(end),
        "interval_minutes": interval_minutes,
        "requirement_basis": basis,
        "ot_budget_cents": ot_budget,
        "intraday_alert_short_threshold": threshold,
        "posture": "OPEN",
        "reforecast_generation": 0,
        "short_interval_count": 0,
        "total_scheduled_hours": q2(0),
        "ot_spend_committed_cents": 0,
        "ot_hours_committed": q2(0),
        "headcount_active": 0,
        "pipeline_fte": q2(0),
        "requirements_locked_at": None,
        "published_at": None,
        "_horizon_start": start,
        "_horizon_end": end,
    })


@bp.get("/planning-cycles/<planning_cycle_id>")
def read_planning_cycle(planning_cycle_id):
    require_auth(CYCLE_READERS)
    return ok(public(get("planning_cycles", planning_cycle_id)))


@bp.get("/planning-cycles")
def list_planning_cycles():
    require_auth(CYCLE_READERS)
    return std_list("planning_cycles", [("posture", "posture")])


@bp.post("/planning-cycles/<planning_cycle_id>/posture")
def drive_posture(planning_cycle_id):
    require_auth(["CapacityPlanner", "SchedulingManager"])
    b = body()
    target = v_enum(b, "target_posture", POSTURES)
    cycle = get("planning_cycles", planning_cycle_id)
    require_not_frozen(cycle)
    current = cycle["posture"]
    if target == "FROZEN":
        set_fields(cycle, {"posture": "FROZEN"})
    elif target == "REQUIREMENTS_LOCKED":
        if current != "OPEN":
            fail("ERR_INVALID_STATE", "REQUIREMENTS_LOCKED is only reachable from OPEN")
        if not any(int(g["interval_count"]) >= 1 for g in calc.cycle_groups(cycle["id"])):
            fail("ERR_INVALID_STATE", "No forecast group of the cycle has an interval grid")
        set_fields(cycle, {"posture": "REQUIREMENTS_LOCKED", "requirements_locked_at": now_iso()})
        recompute_short_interval_count(cycle)
    elif target == "OPEN":
        if current != "REQUIREMENTS_LOCKED":
            fail("ERR_INVALID_STATE", "OPEN is only reachable from REQUIREMENTS_LOCKED")
        if any(s["publication_status"] == "PUBLISHED" for s in shifts_of_cycle(cycle["id"])):
            fail("ERR_CYCLE_NOT_OPEN", "A shift of the cycle is already published")
        set_fields(cycle, {"posture": "OPEN", "requirements_locked_at": None})
    elif target == "SCHEDULE_PUBLISHED":
        if current != "REQUIREMENTS_LOCKED":
            fail("ERR_INVALID_STATE", "SCHEDULE_PUBLISHED is only reachable from REQUIREMENTS_LOCKED")
        if not any(s["publication_status"] == "PUBLISHED" for s in shifts_of_cycle(cycle["id"])):
            fail("ERR_INVALID_STATE", "No shift of the cycle is published")
        set_fields(cycle, {"posture": "SCHEDULE_PUBLISHED", "published_at": now_iso()})
    else:
        fail("ERR_INVALID_STATE", "INTRADAY_ALERT is a system-driven posture")
    return ok(public(cycle))


@bp.post("/planning-cycles/<planning_cycle_id>/reforecast")
def run_reforecast(planning_cycle_id):
    require_auth(["WorkforceAnalyst", "CapacityPlanner"])
    b = body()
    expected = v_int(b, "expected_cycle_version")
    raw_from, effective_from = v_datetime(b, "effective_from_interval_start")
    group_id = v_id(b, "forecast_group_id", required=False)
    cycle = get("planning_cycles", planning_cycle_id)
    scoped = get("forecast_groups", group_id) if group_id is not None else None
    if expected != int(cycle["version"]):
        fail("ERR_STALE_CYCLE_VERSION", "The cycle version echo is stale")
    require_not_frozen(cycle)
    if not in_horizon_instant(cycle, effective_from):
        fail("ERR_INTERVAL_OUTSIDE_HORIZON",
             "effective_from_interval_start falls outside the cycle horizon")
    groups = [scoped] if scoped is not None else calc.cycle_groups(cycle["id"])
    for group in groups:
        intervals = calc.group_intervals(group["id"])
        scored = [
            ip for ip in intervals
            if ip["actual_volume"] is not None and int(ip["volume_forecast"]) > 0
            and ip["_start"] < effective_from
        ]
        scored.sort(key=lambda r: (r["_start"], r["created_at"], r["_seq"]))
        accumulator = D(1)
        for ip in scored:
            ratio = D(ip["actual_volume"]) / D(ip["volume_forecast"])
            accumulator = calc.REFORECAST_ALPHA * ratio + (D(1) - calc.REFORECAST_ALPHA) * accumulator
            set_fields(ip, {"observed_ratio": q4(ratio), "smoothed_ratio": q4(accumulator)})
        multiplier = q4(accumulator)
        if multiplier < calc.REFORECAST_MULTIPLIER_FLOOR:
            multiplier = calc.REFORECAST_MULTIPLIER_FLOOR
        elif multiplier > calc.REFORECAST_MULTIPLIER_CEILING:
            multiplier = calc.REFORECAST_MULTIPLIER_CEILING
        set_fields(group, {"reforecast_multiplier": q4(multiplier)})
        for ip in intervals:
            if ip["_start"] >= effective_from:
                recompute_interval_forecast(ip)
    set_fields(cycle, {"reforecast_generation": int(cycle["reforecast_generation"]) + 1})
    recompute_short_interval_count(cycle)
    return ok(public(cycle))


def in_horizon_date(cycle, day):
    return cycle["_horizon_start"] <= day <= cycle["_horizon_end"]


def in_horizon_instant(cycle, instant):
    from core import date_to_dt
    start = date_to_dt(cycle["_horizon_start"])
    end = date_to_dt(cycle["_horizon_end"]) + timedelta(days=1)
    return start <= instant < end


@bp.get("/planning-cycles/<planning_cycle_id>/coverage-summary")
def coverage_summary(planning_cycle_id):
    require_auth(["CapacityPlanner", "WorkforceAnalyst", "SchedulingManager",
                  "IntradayController", "SourcingManager"])
    cycle = get("planning_cycles", planning_cycle_id)
    service_date = filter_arg("service_date")
    intervals = calc.cycle_intervals(cycle["id"])
    if service_date is not None:
        intervals = [ip for ip in intervals if ip["service_date"] == service_date]
    totals = {
        "planning_cycle_id": cycle["id"],
        "posture": cycle["posture"],
        "interval_count": len(intervals),
        "short_interval_count": int(cycle["short_interval_count"]),
        "total_required_agents": sum(int(ip["required_agents"]) for ip in intervals),
        "total_effective_scheduled_agents": sum(int(ip["effective_scheduled_agents"]) for ip in intervals),
        "total_coverage_gap": sum(int(ip["coverage_gap"]) for ip in intervals),
        "total_allocatable_volume": sum(int(ip["allocatable_volume"]) for ip in intervals),
        "total_partner_committed_volume": sum(int(ip["partner_committed_volume"]) for ip in intervals),
        "total_unserved_volume": sum(int(ip["unserved_volume"]) for ip in intervals),
    }
    return ok(totals)


# ---------------------------------------------------------------------------
# Labour agreements
# ---------------------------------------------------------------------------
@bp.post("/labor-agreements")
def create_labor_agreement():
    require_auth(["CapacityPlanner"])
    from core import new_row
    b = body()
    code = v_string(b, "code", maxlen=40)
    min_rest = v_num(b, "min_rest_hours", exclusive_min=0)
    max_weekly = v_num(b, "max_weekly_hours", exclusive_min=0)
    max_consecutive = v_int(b, "max_consecutive_days", minimum=1)
    vto_notice = v_num(b, "vto_min_notice_hours", minimum=0)
    floor_pct = v_num(b, "preference_honor_floor_pct", minimum=0, maximum=1)
    premium = v_num(b, "ot_premium_multiplier", required=False, minimum=1, default="1.00")
    if any(r["code"] == code for r in rows("labor_agreements")):
        bad("code", "must be unique across all labor agreements")
    row = new_row("labor_agreements", {
        "code": code,
        "min_rest_hours": min_rest,
        "max_weekly_hours": max_weekly,
        "max_consecutive_days": max_consecutive,
        "vto_min_notice_hours": vto_notice,
        "preference_honor_floor_pct": q4(floor_pct),
        "ot_premium_multiplier": premium,
        "enrolled_agent_count": 0,
    })
    return created(public(row))


@bp.get("/labor-agreements/<labor_agreement_id>")
def read_labor_agreement(labor_agreement_id):
    require_auth(CYCLE_READERS)
    return ok(public(get("labor_agreements", labor_agreement_id)))


@bp.get("/labor-agreements")
def list_labor_agreements():
    require_auth(CYCLE_READERS)
    return std_list("labor_agreements", [("code", "code")])
