"""Climate strategies: setpoint windows, energy actuals and cancellation."""
from flask import Blueprint, request

import calc
import const
import fields
from authz import ALL_ROLES, GROWER_MANAGER, body, guard
from envelope import created, ok, paginated, public
from errors import ApiError
from helpers import fetch, filter_equals, occ, terminal, to_status_enum, transition
from money import D, ZERO, q2
from store import base_record, db, now, ordered, touch

bp = Blueprint("climate", __name__)

ALLOWED = {"ACTIVE": ("CANCELLED",)}


@bp.post("/climate-strategies")
@guard([GROWER_MANAGER])
def create_strategy():
    payload = body()
    # priority 4 - presence and type only; the ranges belong to priority 20
    zone_id = fields.string(payload, "zone_id")
    regime = fields.enum_slot(payload, "regime")
    window_start = fields.timestamp(payload, "window_start")
    window_end = fields.timestamp(payload, "window_end")
    temp_setpoint_c = fields.number(payload, "temp_setpoint_c")
    rh_setpoint_pct = fields.number(payload, "rh_setpoint_pct")
    co2_setpoint_ppm = fields.integer(payload, "co2_setpoint_ppm")
    lighting_hours = fields.number(payload, "lighting_hours")
    screen_position_pct = fields.number(payload, "screen_position_pct")
    expected = fields.integer(payload, "expected_zone_version")
    supersede = fields.boolean(payload, "supersede", required=False, default=False)
    # priority 5
    fields.enum_value(regime, "regime", const.CLIMATE_REGIMES)
    # priority 7
    zone = fetch("zones", zone_id)
    # priority 8
    occ(zone, expected, "ERR_STALE_ZONE_VERSION")

    hours = calc.window_hours(window_start, window_end)
    # priority 20 - setpoint ranges, then equipment capability
    if not (D(5) <= temp_setpoint_c <= D(35)):
        raise ApiError("ERR_SETPOINT_OUT_OF_RANGE", "temp_setpoint_c is out of range")
    if not (D(40) <= rh_setpoint_pct <= D(95)):
        raise ApiError("ERR_SETPOINT_OUT_OF_RANGE", "rh_setpoint_pct is out of range")
    if not (400 <= co2_setpoint_ppm <= 1200):
        raise ApiError("ERR_SETPOINT_OUT_OF_RANGE", "co2_setpoint_ppm is out of range")
    if lighting_hours < ZERO:
        raise ApiError("ERR_SETPOINT_OUT_OF_RANGE", "lighting_hours is out of range")
    if window_end > window_start and lighting_hours > hours:
        raise ApiError(
            "ERR_SETPOINT_OUT_OF_RANGE", "lighting_hours exceeds the window duration"
        )
    if not (D(0) <= screen_position_pct <= D(100)):
        raise ApiError("ERR_SETPOINT_OUT_OF_RANGE", "screen_position_pct is out of range")
    if lighting_hours > ZERO and not zone["has_supplemental_lighting"]:
        raise ApiError("ERR_ZONE_CAPABILITY_MISSING", "the zone has no supplemental lighting")
    if screen_position_pct > ZERO and not zone["has_thermal_screen"]:
        raise ApiError("ERR_ZONE_CAPABILITY_MISSING", "the zone has no thermal screen")
    # priority 28
    if window_end <= window_start:
        raise ApiError("ERR_INVALID_WINDOW")
    # priority 29 - half-open overlap inside the same zone AND regime
    clashes = []
    for other in ordered("climate_strategies"):
        if other["zone_id"] != zone_id or other["regime"] != regime:
            continue
        if other["status"] != "ACTIVE":
            continue
        if window_start < other["window_end"] and other["window_start"] < window_end:
            clashes.append(other)
    if clashes and not supersede:
        raise ApiError("ERR_CLIMATE_WINDOW_OVERLAP")

    record = base_record()
    record.update({
        "zone_id": zone_id,
        "regime": regime,
        "window_start": window_start,
        "window_end": window_end,
        "temp_setpoint_c": temp_setpoint_c,
        "rh_setpoint_pct": rh_setpoint_pct,
        "co2_setpoint_ppm": co2_setpoint_ppm,
        "lighting_hours": lighting_hours,
        "screen_position_pct": screen_position_pct,
        "supersede": supersede,
        "expected_zone_version": expected,
        "status": "ACTIVE",
        "window_hours": hours,
        "planned_heat_kwh": None,
        "planned_light_kwh": None,
        "planned_co2_kg": None,
        "projected_energy_cost_usd": None,
        "gas_consumed_m3": None,
        "chp_generated_kwh": None,
        "grid_import_kwh": None,
        "screen_deployed_hours": None,
        "actuals_recorded_at": None,
        "settled_energy_cost_usd": None,
        "cost_variance_usd": None,
    })
    calc.project_energy(record, zone)
    db["climate_strategies"][record["id"]] = record

    for other in clashes:
        # Superseding leaves the older window's recorded actuals untouched.
        other["status"] = "SUPERSEDED"
        touch(other)

    zone["climate_plan_revision"] = zone["climate_plan_revision"] + 1
    calc.refresh_zone(zone, force=True)
    return created(public(record))


@bp.get("/climate-strategies")
@guard(ALL_ROLES)
def list_strategies():
    rows = ordered("climate_strategies")
    rows = filter_equals(rows, "zone_id", request.args.get("zone_id"))
    rows = filter_equals(rows, "regime", request.args.get("regime"))
    rows = filter_equals(rows, "status", request.args.get("status"))
    return paginated(rows, public)


@bp.get("/climate-strategies/<strategy_id>")
@guard(ALL_ROLES)
def get_strategy(strategy_id):
    return ok(public(fetch("climate_strategies", strategy_id)))


@bp.post("/climate-strategies/<strategy_id>/actuals")
@guard([GROWER_MANAGER])
def record_actuals(strategy_id):
    payload = body()
    gas = fields.number(payload, "gas_consumed_m3", lo=0)
    chp = fields.number(payload, "chp_generated_kwh", lo=0)
    grid = fields.number(payload, "grid_import_kwh", lo=0)
    screen_hours = fields.number(payload, "screen_deployed_hours", lo=0)
    strategy = fetch("climate_strategies", strategy_id)
    terminal(strategy["status"], const.CLIMATE_TERMINAL)
    if strategy["actuals_recorded_at"] is not None:
        raise ApiError("ERR_ACTUALS_ALREADY_RECORDED")
    zone = db["zones"][strategy["zone_id"]]

    strategy["gas_consumed_m3"] = q2(gas)
    strategy["chp_generated_kwh"] = q2(chp)
    strategy["grid_import_kwh"] = q2(grid)
    strategy["screen_deployed_hours"] = q2(screen_hours)
    strategy["actuals_recorded_at"] = now()
    calc.settle_energy(strategy, zone)
    touch(strategy)
    return ok(public(strategy))


@bp.post("/climate-strategies/<strategy_id>/transitions")
@guard([GROWER_MANAGER])
def transition_strategy(strategy_id):
    payload = body()
    target = fields.enum_slot(payload, "to_status")
    to_status_enum(target, const.CLIMATE_STATUSES)
    strategy = fetch("climate_strategies", strategy_id)
    terminal(strategy["status"], const.CLIMATE_TERMINAL)
    transition(ALLOWED, strategy["status"], target)
    if strategy["actuals_recorded_at"] is not None:
        raise ApiError("ERR_ACTUALS_ALREADY_RECORDED")
    strategy["status"] = "CANCELLED"
    touch(strategy)
    return ok(public(strategy))
