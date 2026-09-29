"""Fuelling assets, filter changes and hydrant pits."""
from flask import Blueprint, request

import calc
import services as svc
from authz import (auth, body, enum, opt_num, out_of_range, req_int, req_num,
                   req_str, resolve, resolve_ref, rng)
from core import (ApiError, D, base_row, created, db, f2, f4, listing, now_iso,
                  ok, public, touch)
from routes.tanks import new_sample

bp = Blueprint("assets", __name__)

ASSET_TYPES = ("TRUCK", "HYDRANT_CART")
ASSET_STATES = ("IN_SERVICE", "FILTER_DUE", "DOWN_FOR_FILTER", "DOWN_MAINTENANCE")


def asset_view(asset):
    calc.recompute_asset(asset)
    return public(asset)


# ------------------------------------------------------------------ assets
@bp.post("/fuel-farms/<fid>/fueling-assets")
def create_asset(fid):
    auth("ConsortiumAdmin")
    farm = resolve(db.farms, fid, "Fuel farm not found")
    data = body()
    code = req_str(data, "asset_code")
    atype = req_str(data, "asset_type")
    capacity = opt_num(data, "tank_capacity_liters", "0.0")
    buffer_minutes = data.get("turnaround_buffer_minutes")
    if buffer_minutes is None:
        buffer_minutes = 15
    elif not isinstance(buffer_minutes, int) or isinstance(buffer_minutes, bool):
        raise ApiError("ERR_INVALID_PAYLOAD", "turnaround_buffer_minutes must be an integer")
    dp = opt_num(data, "differential_pressure_kpa", "0.0")

    enum(atype, "asset_type", ASSET_TYPES)
    rng(capacity, "tank_capacity_liters", minimum=0)
    if atype == "HYDRANT_CART" and D(capacity) != D(0):
        out_of_range("tank_capacity_liters must be 0 for a HYDRANT_CART")
    rng(buffer_minutes, "turnaround_buffer_minutes", minimum=0)
    rng(dp, "differential_pressure_kpa", minimum=0)

    for a in db.assets.values():
        if a["fuel_farm_id"] == farm["id"] and a["asset_code"] == code:
            raise ApiError("ERR_DUPLICATE_KEY",
                           "asset_code %s already exists at this farm" % code)

    asset = base_row()
    asset.update({
        "fuel_farm_id": farm["id"],
        "asset_code": code,
        "asset_type": atype,
        "tank_capacity_liters": f2(capacity),
        "turnaround_buffer_minutes": int(buffer_minutes),
        "differential_pressure_kpa": f2(dp),
        "liters_since_filter_change": 0.0,
        "last_filter_change_at_utc": now_iso(),
        "element_life_pct": 0.0,
        "reliability_score": 100,
        "onboard_volume_liters": 0.0,
        "status": "IN_SERVICE",
        "_filter_epoch": 0,
    })
    db.assets[asset["id"]] = asset
    calc.recompute_asset(asset)
    svc.refresh_farm(farm)
    return created(public(asset))


@bp.get("/fueling-assets")
def list_assets():
    auth("ConsortiumAdmin", "FarmOperator", "QualityInspector", "IntoPlaneAgent")
    rows = list(db.assets.values())
    for a in rows:
        calc.recompute_asset(a)
    farm_id = request.args.get("fuel_farm_id")
    atype = request.args.get("asset_type")
    status = request.args.get("status")
    if farm_id:
        rows = [a for a in rows if a["fuel_farm_id"] == farm_id]
    if atype:
        rows = [a for a in rows if a["asset_type"] == atype]
    if status:
        rows = [a for a in rows if a["status"] == status]
    return listing(rows)


@bp.get("/fueling-assets/<aid>")
def get_asset(aid):
    auth("ConsortiumAdmin", "FarmOperator", "QualityInspector", "IntoPlaneAgent")
    asset = resolve(db.assets, aid, "Fueling asset not found")
    return ok(asset_view(asset))


@bp.post("/fueling-assets/<aid>/status")
def set_asset_status(aid):
    uid, role = auth("FarmOperator", "ConsortiumAdmin")
    asset = resolve(db.assets, aid, "Fueling asset not found")
    farm = db.farms.get(asset["fuel_farm_id"])
    data = body()
    to_status = req_str(data, "to_status")
    enum(to_status, "to_status", ASSET_STATES)

    calc.recompute_asset(asset)
    current = asset["status"]
    allowed = {("IN_SERVICE", "FILTER_DUE"), ("IN_SERVICE", "DOWN_FOR_FILTER"),
               ("FILTER_DUE", "DOWN_FOR_FILTER"), ("IN_SERVICE", "DOWN_MAINTENANCE"),
               ("FILTER_DUE", "DOWN_MAINTENANCE"), ("DOWN_MAINTENANCE", "IN_SERVICE")}
    if (current, to_status) not in allowed:
        raise ApiError("ERR_INVALID_ASSET_STATE",
                       "Cannot move asset status from %s to %s" % (current, to_status))
    if to_status == "IN_SERVICE" and role != "ConsortiumAdmin":
        raise ApiError("ERR_ROLE_NOT_PERMITTED",
                       "Only a ConsortiumAdmin may return an asset to service")

    if to_status == "DOWN_FOR_FILTER":
        for o in db.orders.values():
            if o.get("fueling_asset_id") == asset["id"] and o["status"] in ("ASSIGNED", "FUELING"):
                raise ApiError("ERR_ASSET_NOT_SERVICEABLE",
                               "An order on this asset is still ASSIGNED or FUELING")
    if to_status == "IN_SERVICE":
        if asset["reliability_score"] < 60:
            raise ApiError("ERR_ASSET_NOT_SERVICEABLE",
                           "reliability_score must have recovered to at least 60")
        if D(asset["element_life_pct"]) >= D("100.0"):
            raise ApiError("ERR_ASSET_NOT_SERVICEABLE",
                           "element_life_pct must be strictly below 100.0")
        svc.frozen_guard(farm)

    asset["status"] = to_status
    calc.recompute_asset(asset, auto_status=False)
    touch(asset)
    if farm is not None:
        svc.refresh_farm(farm)
        touch(farm)
    return ok(public(asset))


# ------------------------------------------------------------------ filter changes
@bp.post("/fueling-assets/<aid>/filter-changes")
def create_filter_change(aid):
    uid, role = auth("QualityInspector")
    asset = resolve(db.assets, aid, "Fueling asset not found")
    farm = db.farms.get(asset["fuel_farm_id"])
    data = body()
    lot = req_str(data, "element_lot_number")
    count = req_int(data, "element_count")
    post_dp = req_num(data, "post_change_differential_pressure_kpa")
    rng(count, "element_count", minimum=1)
    rng(post_dp, "post_change_differential_pressure_kpa", minimum=0)

    calc.recompute_asset(asset)
    if asset["status"] not in ("DOWN_FOR_FILTER", "FILTER_DUE"):
        raise ApiError("ERR_INVALID_ASSET_STATE",
                       "Asset status %s cannot accept a filter change" % asset["status"])
    svc.frozen_guard(farm)

    record = base_row(with_mutable=False)
    record.update({
        "fueling_asset_id": asset["id"],
        "element_lot_number": lot,
        "element_count": int(count),
        "liters_at_change": f2(asset["liters_since_filter_change"]),
        "differential_pressure_before_kpa": f2(asset["differential_pressure_kpa"]),
        "post_change_differential_pressure_kpa": f2(post_dp),
        "changed_by_user_id": uid,
        "changed_at_utc": now_iso(),
    })
    db.filter_changes[record["id"]] = record

    asset["liters_since_filter_change"] = 0.0
    asset["differential_pressure_kpa"] = f2(post_dp)
    asset["last_filter_change_at_utc"] = now_iso()
    asset["status"] = "IN_SERVICE"
    asset["_filter_epoch"] = asset.get("_filter_epoch", 0) + 1
    calc.recompute_asset(asset, auto_status=False)
    touch(asset)
    new_sample("POST_FILTER_CHANGE", uid, asset_id=asset["id"])
    if farm is not None:
        svc.refresh_farm(farm)
        touch(farm)
    return created(public(record))


@bp.get("/fueling-assets/<aid>/filter-changes")
def list_filter_changes(aid):
    auth("ConsortiumAdmin", "FarmOperator", "QualityInspector")
    asset = resolve(db.assets, aid, "Fueling asset not found")
    rows = [r for r in db.filter_changes.values() if r["fueling_asset_id"] == asset["id"]]
    return listing(rows)


# ------------------------------------------------------------------ hydrant pits
@bp.post("/fuel-farms/<fid>/hydrant-pits")
def create_pit(fid):
    auth("ConsortiumAdmin")
    farm = resolve(db.farms, fid, "Fuel farm not found")
    data = body()
    tank = resolve_ref(db.tanks, data.get("source_storage_tank_id"),
                       "Source storage tank not found") if isinstance(
                           data.get("source_storage_tank_id"), str) else None
    pit_code = req_str(data, "pit_code")
    stand = req_str(data, "stand_code")
    tank_id = req_str(data, "source_storage_tank_id")

    for p in db.pits.values():
        if p["fuel_farm_id"] == farm["id"] and p["pit_code"] == pit_code:
            raise ApiError("ERR_DUPLICATE_KEY",
                           "pit_code %s already exists at this farm" % pit_code)
    if not farm["hydrant_system_available"]:
        raise ApiError("ERR_DELIVERY_MODE_MISMATCH",
                       "This farm has no hydrant system available")
    if tank is not None and tank["fuel_farm_id"] != farm["id"]:
        raise ApiError("ERR_CROSS_FARM_REFERENCE",
                       "Source storage tank belongs to a different farm")

    pit = base_row()
    pit.update({
        "fuel_farm_id": farm["id"],
        "pit_code": pit_code,
        "stand_code": stand,
        "source_storage_tank_id": tank_id,
        "status": "AVAILABLE",
    })
    db.pits[pit["id"]] = pit
    return created(public(pit))


@bp.get("/fuel-farms/<fid>/hydrant-pits")
def list_farm_pits(fid):
    auth("ConsortiumAdmin", "FarmOperator", "IntoPlaneAgent")
    farm = resolve(db.farms, fid, "Fuel farm not found")
    rows = [p for p in db.pits.values() if p["fuel_farm_id"] == farm["id"]]
    return listing(rows)


@bp.get("/hydrant-pits")
def list_pits():
    auth("ConsortiumAdmin", "FarmOperator", "IntoPlaneAgent")
    rows = list(db.pits.values())
    farm_id = request.args.get("fuel_farm_id")
    tank_id = request.args.get("source_storage_tank_id")
    status = request.args.get("status")
    if farm_id:
        rows = [p for p in rows if p["fuel_farm_id"] == farm_id]
    if tank_id:
        rows = [p for p in rows if p["source_storage_tank_id"] == tank_id]
    if status:
        rows = [p for p in rows if p["status"] == status]
    return listing(rows)


@bp.get("/hydrant-pits/<pid>")
def get_pit(pid):
    auth("ConsortiumAdmin", "FarmOperator", "IntoPlaneAgent")
    pit = resolve(db.pits, pid, "Hydrant pit not found")
    return ok(public(pit))
