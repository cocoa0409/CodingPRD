"""Routes: energy meter readings."""

from flask import Blueprint

from db import store
from errors import raise_error
from middleware import require_roles, ALL_ROLES
from response import success, list_response
from util import get_body, pagination_params, parse_dt, req_enum, dec, q2
from services.core import (
    stamp_new, get_reading, ser_reading,
    intervals_overlap_half_open, SCOPE_TYPES,
)
from services.calculations import recompute_actual_costs_for_reading

bp = Blueprint("energy", __name__)


def _q(name):
    from flask import request
    v = request.args.get(name)
    return v if v not in (None, "") else None


@bp.post("/energy-readings")
def create_reading():
    require_roles("FarmManager")
    fields = {"scope_type", "zone", "period_start_at", "period_end_at",
              "kwh_consumed", "peak_demand_kw"}
    body = get_body(fields, {"scope_type", "period_start_at", "period_end_at",
                             "kwh_consumed", "peak_demand_kw"})
    scope_type = req_enum(body["scope_type"], "scope_type", SCOPE_TYPES)
    zone = body.get("zone")
    if scope_type == "ZONE":
        if not isinstance(zone, str) or not zone:
            raise_error("ERR_INVALID_REQUEST", "zone required for ZONE scope")
    else:
        if zone is not None:
            raise_error("ERR_INVALID_REQUEST", "zone must be omitted for FACILITY scope")
        zone = None
    p_start = parse_dt(body["period_start_at"], "period_start_at")
    p_end = parse_dt(body["period_end_at"], "period_end_at")
    if p_end <= p_start:
        raise_error("ERR_INVALID_REQUEST", "period_end_at must be after period_start_at")
    kwh = q2(dec(body["kwh_consumed"], "kwh_consumed"))
    peak = q2(dec(body["peak_demand_kw"], "peak_demand_kw"))
    if kwh < 0 or peak < 0:
        raise_error("ERR_INVALID_REQUEST", "kwh/peak must be non-negative")
    # half-open overlap per (scope_type, zone) partition key
    for r in store.energy_readings.values():
        if r["scope_type"] != scope_type or r.get("zone") != zone:
            continue
        if intervals_overlap_half_open(p_start, p_end, r["period_start_at"], r["period_end_at"]):
            raise_error("ERR_ENERGY_PERIOD_OVERLAP", "Energy period overlap")
    reading = stamp_new({
        "scope_type": scope_type, "zone": zone,
        "period_start_at": p_start, "period_end_at": p_end,
        "kwh_consumed": kwh, "peak_demand_kw": peak,
    }, with_version=False)
    store.energy_readings[reading["id"]] = reading
    recompute_actual_costs_for_reading(reading)
    return success(ser_reading(reading), status=201)


@bp.get("/energy-readings")
def list_readings():
    require_roles(*ALL_ROLES)
    limit, offset = pagination_params()
    items = list(store.energy_readings.values())
    st = _q("scope_type")
    zn = _q("zone")
    if st is not None:
        items = [r for r in items if r["scope_type"] == st]
    if zn is not None:
        items = [r for r in items if r.get("zone") == zn]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    return list_response(items, ser_reading, limit, offset)


@bp.get("/energy-readings/<rid>")
def get_reading_route(rid):
    require_roles(*ALL_ROLES)
    return success(ser_reading(get_reading(rid)))
