"""Station routes: create, get, run_ops_checkpoint."""
from flask import Blueprint, request

import db
import errors
import middleware
import response
import serializers
import util
from services import calc, derived

bp = Blueprint("stations", __name__)


@bp.route("/deice-ops/stations", methods=["POST"])
def create_station():
    middleware.require_roles("StationAdmin")
    payload = request.get_json(silent=True) or {}
    util.require_fields(payload, ["code", "name"])
    code = payload["code"]
    name = payload["name"]
    if not isinstance(code, str) or not code:
        raise errors.invalid_request("code must be a non-empty string")
    if not isinstance(name, str) or not name:
        raise errors.invalid_request("name must be a non-empty string")
    # Uniqueness of code across stations.
    for s in db.stations.values():
        if s["code"] == code:
            raise errors.invalid_request("code must be unique across stations")
    min_collection_pct = payload.get("min_collection_pct", 50.0)
    fluid_ops_minimum_liters = payload.get("fluid_ops_minimum_liters", 2000)
    storm_surcharge_pct = payload.get("storm_surcharge_pct", 25)
    min_collection_pct = float(util.to_decimal(min_collection_pct, "min_collection_pct"))
    fluid_ops_minimum_liters = util.to_int(fluid_ops_minimum_liters, "fluid_ops_minimum_liters")
    storm_surcharge_pct = float(util.to_decimal(storm_surcharge_pct, "storm_surcharge_pct"))
    now = util.iso_now()
    station = {
        "id": util.new_id(),
        "code": code,
        "name": name,
        "min_collection_pct": min_collection_pct,
        "fluid_ops_minimum_liters": fluid_ops_minimum_liters,
        "storm_surcharge_pct": storm_surcharge_pct,
        "posture": "NORMAL",
        "active_supply_alert": False,
        "collected_pool_liters": 0,
        "ops_epoch_index": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    station["_created_dt"] = db.get_clock()
    db.stations[station["id"]] = station
    return response.success_object(serializers.station(station), 201)


@bp.route("/deice-ops/stations/<sid>", methods=["GET"])
def get_station(sid):
    middleware.require_roles(
        "StationAdmin",
        "PadOperator",
        "EnvironmentalOfficer",
        "BillingClerk",
        "AirlineRep",
        "Inspector",
    )
    station = db.stations.get(sid)
    if station is None:
        raise errors.not_found("station not found")
    derived.recompute_station_all(sid)
    return response.success_object(serializers.station(station), 200)


@bp.route("/deice-ops/stations/<sid>/run_ops_checkpoint", methods=["POST"])
def run_ops_checkpoint(sid):
    middleware.require_roles("StationAdmin")
    station = db.stations.get(sid)
    if station is None:
        raise errors.not_found("station not found")
    now_dt = db.get_clock()
    # 1. epoch += 1
    station["ops_epoch_index"] = station.get("ops_epoch_index", 0) + 1
    station["version"] += 1
    station["updated_at"] = util.iso_now()
    # 2. QUEUED/DEFERRED requests in queue order: epochs_in_queue += 1; >=2 -> EXPIRED
    candidates = [
        r
        for r in db.deice_requests.values()
        if r["station_id"] == sid and r["status"] in ("QUEUED", "DEFERRED")
    ]
    candidates.sort(key=calc.queue_sort_key)
    for r in candidates:
        r["epochs_in_queue"] = r.get("epochs_in_queue", 0) + 1
        if r["epochs_in_queue"] >= calc.EXPIRE_EPOCHS:
            r["status"] = "EXPIRED"
        r["updated_at"] = util.iso_now()
    # 3. Permits ACTIVE/SUSPENDED with effective_to < now -> EXPIRED
    for p in db.discharge_permits.values():
        if p["station_id"] == sid and p["status"] in ("ACTIVE", "SUSPENDED"):
            if p["_effective_to_dt"] < now_dt:
                p["status"] = "EXPIRED"
                p["updated_at"] = util.iso_now()
                p["version"] += 1
    # 4. Recompute all tanks, posture, alert.
    derived.recompute_station_all(sid)
    return response.success_object(serializers.station(station), 200)
