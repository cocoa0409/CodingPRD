"""Storage tanks: registration, service dimension, quality dimension, gauging."""
from flask import Blueprint, request

import calc
import services as svc
from authz import (auth, body, enum, opt_num, out_of_range, req_dt, req_num,
                   req_str, resolve, rng)
from core import (ApiError, D, base_row, created, db, f2, fmt_dt, listing, now,
                  now_iso, ok, parse_dt, public, touch)

bp = Blueprint("tanks", __name__)

SERVICE_STATES = ("IN_SERVICE", "ISOLATED", "OUT_OF_SERVICE")
QUALITY_STATES = ("ON_TEST", "RELEASED", "QUARANTINED")
SAMPLE_PURPOSES = ("RECEIPT_QC", "PERIODIC_TANK_QA", "POST_FILTER_CHANGE")


def tank_view(tank):
    calc.recompute_tank(tank)
    return public(tank)


def new_sample(purpose, drawn_by, receipt_id=None, tank_id=None, asset_id=None):
    s = base_row()
    s.update({
        "fuel_receipt_id": receipt_id,
        "storage_tank_id": tank_id,
        "fueling_asset_id": asset_id,
        "sample_purpose": purpose,
        "drawn_by_user_id": drawn_by,
        "tested_by_user_id": None,
        "water_reaction_rating": None,
        "particulate_mg_per_l": None,
        "conductivity_ps_per_m": None,
        "observed_density_kg_per_m3": None,
        "flash_point_c": None,
        "verdict": None,
        "failed_metrics": [],
        "status": "DRAWN",
    })
    db.samples[s["id"]] = s
    return s


# ------------------------------------------------------------------ registration
@bp.post("/fuel-farms/<fid>/storage-tanks")
def create_tank(fid):
    auth("ConsortiumAdmin")
    farm = resolve(db.farms, fid, "Fuel farm not found")
    data = body()
    code = req_str(data, "tank_code")
    capacity = req_num(data, "capacity_liters")
    safe_fill = req_num(data, "safe_fill_liters")
    density = req_num(data, "density_kg_per_m3")
    opening = opt_num(data, "opening_volume_liters", "0.0")

    rng(capacity, "capacity_liters", minimum=0, exclusive_min=True)
    rng(safe_fill, "safe_fill_liters", minimum=0, exclusive_min=True)
    if D(safe_fill) > D(capacity):
        out_of_range("safe_fill_liters must not exceed capacity_liters")
    rng(density, "density_kg_per_m3", minimum=750, maximum=850)
    rng(opening, "opening_volume_liters", minimum=0)
    if D(opening) > D(safe_fill):
        out_of_range("opening_volume_liters must not exceed safe_fill_liters")

    for t in db.tanks.values():
        if t["fuel_farm_id"] == farm["id"] and t["tank_code"] == code:
            raise ApiError("ERR_DUPLICATE_KEY", "tank_code %s already exists at this farm" % code)

    tank = base_row()
    tank.update({
        "fuel_farm_id": farm["id"],
        "tank_code": code,
        "capacity_liters": f2(capacity),
        "safe_fill_liters": f2(safe_fill),
        "density_kg_per_m3": f2(density),
        "opening_volume_liters": f2(opening),
        "book_volume_liters": 0.0,
        "reserved_volume_liters": 0.0,
        "available_volume_liters": 0.0,
        "service_status": "IN_SERVICE",
        "quality_status": "ON_TEST",
        "isolation_window_start_utc": None,
        "isolation_window_end_utc": None,
        "last_gauge_volume_liters": None,
        "last_gauge_at_utc": None,
        "water_bottom_mm": 0.0,
    })
    db.tanks[tank["id"]] = tank
    calc.recompute_tank(tank)
    svc.refresh_farm(farm)
    return created(public(tank))


@bp.get("/fuel-farms/<fid>/storage-tanks")
def list_farm_tanks(fid):
    auth("ConsortiumAdmin", "FarmOperator", "QualityInspector", "IntoPlaneAgent")
    farm = resolve(db.farms, fid, "Fuel farm not found")
    rows = [t for t in db.tanks.values() if t["fuel_farm_id"] == farm["id"]]
    ss = request.args.get("service_status")
    qs = request.args.get("quality_status")
    if ss:
        rows = [t for t in rows if t["service_status"] == ss]
    if qs:
        rows = [t for t in rows if t["quality_status"] == qs]
    for t in rows:
        calc.recompute_tank(t)
    return listing(rows)


@bp.get("/storage-tanks/<tid>")
def get_tank(tid):
    auth("ConsortiumAdmin", "FarmOperator", "QualityInspector", "IntoPlaneAgent")
    tank = resolve(db.tanks, tid, "Storage tank not found")
    return ok(tank_view(tank))


# ------------------------------------------------------------------ service dim
@bp.post("/storage-tanks/<tid>/service-status")
def service_status(tid):
    uid, role = auth("FarmOperator", "ConsortiumAdmin")
    tank = resolve(db.tanks, tid, "Storage tank not found")
    farm = db.farms.get(tank["fuel_farm_id"])
    data = body()
    to_status = req_str(data, "to_status")
    enum(to_status, "to_status", SERVICE_STATES)
    win_start = win_end = None
    if to_status == "ISOLATED":
        win_start = req_dt(data, "isolation_window_start_utc")
        win_end = req_dt(data, "isolation_window_end_utc")
        if win_end <= win_start:
            out_of_range("isolation_window_end_utc must be later than isolation_window_start_utc")
    if to_status == "OUT_OF_SERVICE" and role != "ConsortiumAdmin":
        raise ApiError("ERR_ROLE_NOT_PERMITTED", "Only a ConsortiumAdmin may retire a tank")

    current = tank["service_status"]
    allowed = {("IN_SERVICE", "ISOLATED"), ("ISOLATED", "IN_SERVICE"),
               ("ISOLATED", "OUT_OF_SERVICE")}
    if (current, to_status) not in allowed:
        raise ApiError("ERR_INVALID_TANK_STATE",
                       "Cannot move tank service_status from %s to %s" % (current, to_status))

    calc.recompute_tank(tank)
    if to_status == "IN_SERVICE":
        if tank["quality_status"] == "QUARANTINED":
            raise ApiError("ERR_INVALID_TANK_STATE", "Tank quality_status is QUARANTINED")
        if D(tank["water_bottom_mm"]) >= D("25.0"):
            raise ApiError("ERR_WATER_BOTTOM_EXCEEDED", "Water bottom is at or above 25.0 mm")
        tank["service_status"] = "IN_SERVICE"
        tank["isolation_window_start_utc"] = None
        tank["isolation_window_end_utc"] = None
    elif to_status == "ISOLATED":
        for o in calc.tank_orders(tank["id"]):
            if o["status"] in ("ASSIGNED", "FUELING"):
                raise ApiError("ERR_TANK_ISOLATION_CONFLICT",
                               "An order on this tank is still ASSIGNED or FUELING")
        for other in calc.farm_tanks(tank["fuel_farm_id"]):
            if other["id"] == tank["id"] or other["service_status"] != "ISOLATED":
                continue
            os_ = parse_dt(other.get("isolation_window_start_utc")) if other.get("isolation_window_start_utc") else None
            oe = parse_dt(other.get("isolation_window_end_utc")) if other.get("isolation_window_end_utc") else None
            if os_ is None or oe is None:
                raise ApiError("ERR_TANK_ISOLATION_CONFLICT",
                               "Another tank at the farm is already ISOLATED")
            if win_start < oe and os_ < win_end:
                raise ApiError("ERR_TANK_ISOLATION_CONFLICT",
                               "Isolation window overlaps another isolated tank")
        tank["service_status"] = "ISOLATED"
        tank["isolation_window_start_utc"] = fmt_dt(win_start)
        tank["isolation_window_end_utc"] = fmt_dt(win_end)
    else:
        unpumpable = D(farm["unpumpable_bottom_liters"]) if farm else D(0)
        if D(tank["book_volume_liters"]) > unpumpable:
            raise ApiError("ERR_INVALID_TANK_STATE",
                           "Tank must be drained to the unpumpable heel before retirement")
        tank["service_status"] = "OUT_OF_SERVICE"
        tank["isolation_window_start_utc"] = None
        tank["isolation_window_end_utc"] = None
        for pit in db.pits.values():
            if pit.get("source_storage_tank_id") == tank["id"] and pit["status"] != "LOCKED_OUT":
                pit["status"] = "LOCKED_OUT"
                touch(pit)

    calc.recompute_tank(tank)
    touch(tank)
    if farm is not None:
        svc.apply_posture_change(farm)
        touch(farm)
    return ok(tank_view(tank))


# ------------------------------------------------------------------ quality dim
@bp.post("/storage-tanks/<tid>/samples")
def draw_tank_sample(tid):
    uid, role = auth("QualityInspector")
    tank = resolve(db.tanks, tid, "Storage tank not found")
    farm = db.farms.get(tank["fuel_farm_id"])
    data = body()
    purpose = req_str(data, "sample_purpose")
    enum(purpose, "sample_purpose", SAMPLE_PURPOSES)

    returning = tank["quality_status"] == "QUARANTINED"
    if returning:
        for r in calc.tank_receipts(tank["id"]):
            if r["status"] == "QUARANTINED":
                raise ApiError("ERR_INVALID_TANK_STATE",
                               "A receipt targeting this tank is still QUARANTINED")
    svc.frozen_guard(farm)

    sample = new_sample(purpose, uid, tank_id=tank["id"])
    if returning:
        tank["quality_status"] = "ON_TEST"
    calc.recompute_tank(tank)
    touch(tank)
    if farm is not None:
        svc.refresh_farm(farm)
        touch(farm)
    return created(public(sample))


@bp.post("/storage-tanks/<tid>/quality-release")
def quality_release(tid):
    uid, role = auth("QualityInspector")
    tank = resolve(db.tanks, tid, "Storage tank not found")
    farm = db.farms.get(tank["fuel_farm_id"])
    body()
    if tank["quality_status"] != "ON_TEST":
        raise ApiError("ERR_INVALID_TANK_STATE",
                       "Tank quality_status is %s, not ON_TEST" % tank["quality_status"])
    sample = svc.latest_periodic_pass(tank["id"])
    if sample is None:
        raise ApiError("ERR_INVALID_TANK_STATE",
                       "No latest PASSing PERIODIC_TANK_QA sample exists for this tank")
    if uid == sample.get("drawn_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The inspector who drew the governing sample may not release the tank")
    if D(tank["water_bottom_mm"]) >= D("25.0"):
        raise ApiError("ERR_WATER_BOTTOM_EXCEEDED", "Water bottom is at or above 25.0 mm")

    tank["quality_status"] = "RELEASED"
    calc.recompute_tank(tank)
    touch(tank)
    if farm is not None:
        svc.refresh_farm(farm)
        touch(farm)
    return ok(tank_view(tank))


@bp.post("/storage-tanks/<tid>/quarantine")
def quarantine(tid):
    auth("QualityInspector")
    tank = resolve(db.tanks, tid, "Storage tank not found")
    farm = db.farms.get(tank["fuel_farm_id"])
    body()
    if tank["quality_status"] != "RELEASED":
        raise ApiError("ERR_INVALID_TANK_STATE",
                       "Tank quality_status is %s, not RELEASED" % tank["quality_status"])
    svc.quarantine_tank(tank)
    touch(tank)
    if farm is not None:
        svc.refresh_farm(farm)
        touch(farm)
    return ok(tank_view(tank))


@bp.post("/storage-tanks/<tid>/gauge-measurements")
def gauge(tid):
    auth("FarmOperator")
    tank = resolve(db.tanks, tid, "Storage tank not found")
    farm = db.farms.get(tank["fuel_farm_id"])
    data = body()
    measured = req_num(data, "measured_volume_liters")
    temperature = req_num(data, "temperature_c")
    water = req_num(data, "water_bottom_mm")
    rng(measured, "measured_volume_liters", minimum=0)
    rng(temperature, "temperature_c", minimum=-20, maximum=60)
    rng(water, "water_bottom_mm", minimum=0)

    tank["last_gauge_volume_liters"] = f2(measured)
    tank["last_gauge_at_utc"] = now_iso()
    tank["water_bottom_mm"] = f2(water)
    # PRD frames every route into quarantine as one transition: "Quarantining a tank,
    # `RELEASED → QUARANTINED`, arrives by three different routes: ... or a gauge measurement
    # reporting free water at or above 25.0 millimetres." The gauge route therefore fires only
    # from `RELEASED`; a tank already `ON_TEST` simply records the depth and stays on test.
    if D(water) >= D("25.0") and tank["quality_status"] == "RELEASED":
        svc.quarantine_tank(tank)
    calc.recompute_tank(tank)
    touch(tank)
    if farm is not None:
        svc.refresh_farm(farm)
        touch(farm)
    return ok(tank_view(tank))
