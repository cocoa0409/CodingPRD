"""Forecast groups, interval grids, marketing drivers and actuals (PRD 3.2, 3.3)."""
from datetime import timedelta

from flask import Blueprint

import calc
from cascade import (
    require_not_frozen, set_fields, recompute_short_interval_count,
    recompute_interval_forecast, recompute_interval_count,
)
from core import (
    D, bad, body, created, date_to_dt, envelope, fail, get, iso3, iso_date, new_row,
    now_dt, ok, public, q4, rows, require_auth, v_array, v_date, v_datetime, v_enum,
    v_id, v_int, v_num, v_number_array, v_skill, v_string,
)
from listing import std_list
from routes_planning import CYCLE_READERS, in_horizon_date

bp = Blueprint("demand", __name__)

CHANNELS = ("VOICE", "CHAT", "EMAIL", "SOCIAL")
EVENT_READERS = ["CapacityPlanner", "WorkforceAnalyst", "SchedulingManager",
                 "IntradayController", "SourcingManager"]
INTERVAL_READERS = ["CapacityPlanner", "WorkforceAnalyst", "SchedulingManager",
                    "IntradayController", "SourcingManager", "TeamCoach"]


# ---------------------------------------------------------------------------
# Forecast groups
# ---------------------------------------------------------------------------
@bp.post("/forecast-groups")
def create_forecast_group():
    require_auth(["WorkforceAnalyst"])
    b = body()
    cycle_id = v_id(b, "planning_cycle_id")
    channel = v_enum(b, "channel", CHANNELS)
    skill_code = v_skill(b, "skill_code")
    base_volume = v_int(b, "base_daily_volume", minimum=0)
    base_aht = v_int(b, "base_aht_seconds", minimum=1)
    start_minute = v_int(b, "operating_start_minute", minimum=0)
    if start_minute >= 1440:
        bad("operating_start_minute", "must be strictly less than 1440")
    end_minute = v_int(b, "operating_end_minute", maximum=1440)
    if end_minute <= start_minute:
        bad("operating_end_minute", "must be strictly greater than operating_start_minute")
    curve = v_number_array(b, "intraday_curve", exclusive_min=0)
    dow = v_number_array(b, "dow_multipliers", length=7, minimum=0)
    slt = v_num(b, "service_level_target_pct", exclusive_min=0, maximum=1)
    sl_seconds = v_int(b, "service_level_seconds", minimum=1)
    occupancy = v_num(b, "occupancy_target_pct", exclusive_min=0, maximum=1)
    shrinkage = v_num(b, "shrinkage_pct", minimum=0)
    if shrinkage >= D(1):
        bad("shrinkage_pct", "must be strictly less than 1")
    cycle = get("planning_cycles", cycle_id)
    width = int(cycle["interval_minutes"])
    if start_minute % width != 0:
        bad("operating_start_minute", "must be a multiple of the cycle interval width")
    if end_minute % width != 0:
        bad("operating_end_minute", "must be a multiple of the cycle interval width")
    if len(curve) != (end_minute - start_minute) // width:
        bad("intraday_curve", "length must equal the operating window width divided by the cycle interval width")
    require_not_frozen(cycle)
    if cycle["posture"] != "OPEN":
        fail("ERR_CYCLE_NOT_OPEN", "Forecast groups may only be created while the cycle is OPEN")
    row = new_row("forecast_groups", {
        "planning_cycle_id": cycle["id"],
        "channel": channel,
        "skill_code": skill_code,
        "base_daily_volume": base_volume,
        "base_aht_seconds": base_aht,
        "operating_start_minute": start_minute,
        "operating_end_minute": end_minute,
        "intraday_curve": curve,
        "dow_multipliers": dow,
        "service_level_target_pct": q4(slt),
        "service_level_seconds": sl_seconds,
        "occupancy_target_pct": q4(occupancy),
        "shrinkage_pct": q4(shrinkage),
        "reforecast_multiplier": q4(1),
        "interval_count": 0,
    })
    return created(public(row))


@bp.get("/forecast-groups/<forecast_group_id>")
def read_forecast_group(forecast_group_id):
    require_auth(CYCLE_READERS)
    return ok(public(get("forecast_groups", forecast_group_id)))


@bp.get("/forecast-groups")
def list_forecast_groups():
    require_auth(CYCLE_READERS)
    return std_list("forecast_groups", [
        ("planning_cycle_id", "planning_cycle_id"),
        ("channel", "channel"),
        ("skill_code", "skill_code"),
    ])


@bp.post("/forecast-groups/<forecast_group_id>/interval-plans")
def generate_interval_plans(forecast_group_id):
    require_auth(["WorkforceAnalyst"])
    b = body()
    service_date = v_date(b, "service_date")
    group = get("forecast_groups", forecast_group_id)
    cycle = calc.cycle_of_group(group)
    require_not_frozen(cycle)
    if cycle["posture"] != "OPEN":
        fail("ERR_CYCLE_NOT_OPEN", "Interval grids may only be generated while the cycle is OPEN")
    if not in_horizon_date(cycle, service_date):
        fail("ERR_INTERVAL_OUTSIDE_HORIZON", "service_date falls outside the cycle horizon")
    iso = iso_date(service_date)
    for existing in calc.group_intervals(group["id"]):
        if existing["service_date"] == iso:
            fail("ERR_DUPLICATE_INTERVALS", "The interval grid for this group and date already exists")
    width = int(cycle["interval_minutes"])
    count = (int(group["operating_end_minute"]) - int(group["operating_start_minute"])) // width
    minted = []
    for index in range(count):
        start = date_to_dt(service_date, int(group["operating_start_minute"]) + index * width)
        end = start + timedelta(minutes=width)
        row = new_row("interval_plans", {
            "forecast_group_id": group["id"],
            "service_date": iso,
            "interval_index": index,
            "interval_start": iso3(start),
            "interval_end": iso3(end),
            "volume_forecast": 0,
            "aht_forecast_seconds": 0,
            "applied_event_uplift_pct": q4(0),
            "required_service_level": 0,
            "required_occupancy_capped": 0,
            "required_agents": 0,
            "scheduled_agents": 0,
            "routing_inflow_agents": 0,
            "routing_outflow_agents": 0,
            "effective_scheduled_agents": 0,
            "coverage_gap": 0,
            "coverage_state": "COVERED",
            "internal_capacity_volume": 0,
            "allocatable_volume": 0,
            "partner_committed_volume": 0,
            "unserved_volume": 0,
            "actual_volume": None,
            "actual_aht_seconds": None,
            "observed_ratio": None,
            "smoothed_ratio": None,
            "_start": start,
            "_end": end,
            "_date": service_date,
        })
        minted.append(row)
    for row in minted:
        recompute_interval_forecast(row)
    recompute_interval_count(group)
    recompute_short_interval_count(cycle)
    return envelope([public(r) for r in minted], "array", 201)


# ---------------------------------------------------------------------------
# Marketing events
# ---------------------------------------------------------------------------
def event_intervals(event, group_scope=None):
    """Interval plans of the event's cycle, in its scope, overlapping its window."""
    out = []
    for group in calc.cycle_groups(event["planning_cycle_id"]):
        if event["forecast_group_id"] is not None:
            if group["id"] != event["forecast_group_id"]:
                continue
        elif event["channel_scope"] != group["channel"]:
            continue
        for ip in calc.group_intervals(group["id"]):
            if calc.overlaps(ip["_start"], ip["_end"], event["_ws"], event["_we"]):
                out.append(ip)
    return out


@bp.post("/marketing-events")
def create_marketing_event():
    require_auth(["WorkforceAnalyst"])
    b = body()
    cycle_id = v_id(b, "planning_cycle_id")
    group_id = v_id(b, "forecast_group_id", required=False)
    channel_scope = v_enum(b, "channel_scope", CHANNELS, required=False)
    supersedes_id = v_id(b, "supersedes_event_id", required=False)
    name = v_string(b, "name", maxlen=80)
    uplift = v_num(b, "uplift_pct", exclusive_min=0, maximum=3)
    tier = v_enum(b, "confidence_tier", ("HIGH", "MEDIUM", "LOW"))
    raw_start, window_start = v_datetime(b, "window_start")
    raw_end, window_end = v_datetime(b, "window_end")
    if group_id is not None and channel_scope is not None:
        bad("channel_scope", "is forbidden when forecast_group_id is supplied")
    if group_id is None and channel_scope is None:
        bad("channel_scope", "is required when forecast_group_id is absent")
    cycle = get("planning_cycles", cycle_id)
    if group_id is not None:
        get("forecast_groups", group_id)
    if supersedes_id is not None:
        get("marketing_events", supersedes_id)
    require_not_frozen(cycle)
    if window_end <= window_start:
        fail("ERR_EVENT_WINDOW_INVALID", "window_end must be strictly after window_start")
    row = new_row("marketing_events", {
        "planning_cycle_id": cycle["id"],
        "forecast_group_id": group_id,
        "channel_scope": channel_scope,
        "supersedes_event_id": supersedes_id,
        "name": name,
        "uplift_pct": q4(uplift),
        "confidence_tier": tier,
        "window_start": raw_start,
        "window_end": raw_end,
        "status": "DRAFT",
        "weighted_uplift_pct": q4(D(uplift) * calc.CONFIDENCE_WEIGHT[tier]),
        "_ws": window_start,
        "_we": window_end,
    })
    return created(public(row))


@bp.get("/marketing-events/<marketing_event_id>")
def read_marketing_event(marketing_event_id):
    require_auth(EVENT_READERS)
    return ok(public(get("marketing_events", marketing_event_id)))


@bp.get("/marketing-events")
def list_marketing_events():
    require_auth(EVENT_READERS)
    return std_list("marketing_events", [
        ("planning_cycle_id", "planning_cycle_id"),
        ("forecast_group_id", "forecast_group_id"),
        ("supersedes_event_id", "supersedes_event_id"),
        ("status", "status"),
    ])


@bp.post("/marketing-events/<marketing_event_id>/status")
def drive_marketing_event(marketing_event_id):
    require_auth(["WorkforceAnalyst"])
    b = body()
    target = v_enum(b, "target_status", ("DRAFT", "CONFIRMED", "CANCELLED", "REALIZED"))
    event = get("marketing_events", marketing_event_id)
    cycle = get("planning_cycles", event["planning_cycle_id"])
    require_not_frozen(cycle)
    current = event["status"]
    if current == "DRAFT" and target == "CONFIRMED":
        if event["_we"] <= event["_ws"]:
            fail("ERR_EVENT_WINDOW_INVALID", "window_end must be strictly after window_start")
        affected = list(event_intervals(event))
        set_fields(event, {"status": "CONFIRMED"})
        superseded = None
        if event["supersedes_event_id"] is not None:
            candidate = get("marketing_events", event["supersedes_event_id"])
            if candidate["status"] == "CONFIRMED":
                superseded = candidate
                affected.extend(event_intervals(candidate))
                set_fields(candidate, {"status": "CANCELLED"})
        seen = set()
        for ip in affected:
            if ip["id"] in seen:
                continue
            seen.add(ip["id"])
            recompute_interval_forecast(ip)
        recompute_short_interval_count(cycle)
    elif current == "DRAFT" and target == "CANCELLED":
        set_fields(event, {"status": "CANCELLED"})
    elif current == "CONFIRMED" and target == "CANCELLED":
        affected = event_intervals(event)
        set_fields(event, {"status": "CANCELLED"})
        for ip in affected:
            recompute_interval_forecast(ip)
        recompute_short_interval_count(cycle)
    elif current == "CONFIRMED" and target == "REALIZED":
        if now_dt() < event["_we"]:
            fail("ERR_EVENT_WINDOW_INVALID", "The logical clock has not reached window_end")
        set_fields(event, {"status": "REALIZED"})
    else:
        fail("ERR_INVALID_STATE", "%s is not reachable from %s" % (target, current))
    return ok(public(event))


# ---------------------------------------------------------------------------
# Interval plans
# ---------------------------------------------------------------------------
@bp.get("/interval-plans/<interval_plan_id>")
def read_interval_plan(interval_plan_id):
    require_auth(INTERVAL_READERS)
    return ok(public(get("interval_plans", interval_plan_id)))


@bp.get("/interval-plans")
def list_interval_plans():
    require_auth(INTERVAL_READERS)
    return std_list("interval_plans", [
        ("forecast_group_id", "forecast_group_id"),
        ("service_date", "service_date"),
        ("coverage_state", "coverage_state"),
    ])


@bp.post("/interval-plans/<interval_plan_id>/actuals")
def post_actuals(interval_plan_id):
    require_auth(["IntradayController", "WorkforceAnalyst"])
    b = body()
    actual_volume = v_int(b, "actual_volume", minimum=0)
    actual_aht = v_int(b, "actual_aht_seconds", minimum=0)
    ip = get("interval_plans", interval_plan_id)
    cycle = calc.cycle_of_interval(ip)
    require_not_frozen(cycle)
    volume_forecast = int(ip["volume_forecast"])
    ratio = None if volume_forecast == 0 else q4(D(actual_volume) / D(volume_forecast))
    set_fields(ip, {
        "actual_volume": actual_volume,
        "actual_aht_seconds": actual_aht,
        "observed_ratio": ratio,
    })
    recompute_short_interval_count(cycle)
    return ok(public(ip))
