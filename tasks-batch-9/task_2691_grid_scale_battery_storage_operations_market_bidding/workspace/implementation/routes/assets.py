"""Storage assets (PRD 3.1) and the logical clock (PRD 2.8)."""

from flask import Blueprint

import db
import errors
import middleware
import response
import validators as v
from errors import ApiError
from services import core

bp = Blueprint("assets", __name__)

SAFETY_STATES = ("NORMAL", "ELEVATED", "ALARM", "LOCKOUT")
MARKET_STATES = ("OFFLINE", "AVAILABLE", "SUSPENDED")


@bp.post("/storage-assets")
def register_asset():
    middleware.authorize("PlatformAdmin")
    body = v.json_body()

    name = v.text(body, "name", min_len=1, max_len=120)
    nameplate = v.num(body, "nameplate_energy_mwh", gt=0)
    power_rating = v.num(body, "power_rating_mw", gt=0)
    poi_mw = v.num(body, "poi_mw_limit", gt=0)
    poi_mva = v.num(body, "poi_mva_limit", ge=poi_mw)
    reactive = v.num(body, "reactive_capability_mvar", ge=0)
    initial_soc = v.num(body, "initial_soc_mwh", ge=0, le=nameplate)
    degradation_cost = v.num(body, "degradation_cost_usd_per_mwh", ge=0)
    warranty_limit = v.num(body, "warranty_throughput_limit_mwh", gt=0)
    cod_raw, _cod = v.timestamp(body, "commercial_operation_date")
    cycle_limit = v.num(body, "cycle_limit_per_year", gt=0)

    rte = v.num(body, "round_trip_efficiency_pct", required=False, default=88.0,
                ge=50.0, le=100.0)
    soc_ceiling = v.num(body, "soc_ceiling_pct", required=False, default=95.0,
                        le=100.0)
    soc_floor = v.num(body, "soc_floor_pct", required=False, default=10.0, ge=0.0,
                      lt=soc_ceiling)
    if not soc_ceiling > soc_floor:
        raise errors.bad_request(
            "Field 'soc_ceiling_pct' must be strictly above 'soc_floor_pct'.")
    initial_throughput = v.num(body, "initial_cumulative_throughput_mwh",
                               required=False, default=0.0, ge=0,
                               lt=warranty_limit)
    guaranteed_soh = v.num(body, "warranty_guaranteed_soh_pct", required=False,
                           default=80.0, gt=0, le=100)
    annual_fade = v.num(body, "warranty_annual_fade_pct", required=False,
                        default=2.5, ge=0)

    asset = db.new_row()
    asset.update({
        "name": name,
        "nameplate_energy_mwh": nameplate,
        "power_rating_mw": power_rating,
        "poi_mw_limit": poi_mw,
        "poi_mva_limit": poi_mva,
        "reactive_capability_mvar": reactive,
        "round_trip_efficiency_pct": rte,
        "soc_floor_pct": soc_floor,
        "soc_ceiling_pct": soc_ceiling,
        "initial_soc_mwh": initial_soc,
        "initial_cumulative_throughput_mwh": initial_throughput,
        "degradation_cost_usd_per_mwh": degradation_cost,
        "warranty_throughput_limit_mwh": warranty_limit,
        "warranty_guaranteed_soh_pct": guaranteed_soh,
        "warranty_annual_fade_pct": annual_fade,
        "commercial_operation_date": cod_raw,
        "cycle_limit_per_year": cycle_limit,
        "soc_mwh": initial_soc,
        "cumulative_throughput_mwh": initial_throughput,
        "equivalent_full_cycles_ytd": 0.0,
        "reserved_mwh_total": 0.0,
        "free_dispatchable_mwh": 0.0,
        "soh_pct": 100.0,
        "rated_energy_mwh": 0.0,
        "available_energy_mwh": 0.0,
        "safety_state": "NORMAL",
        "market_state": "OFFLINE",
        "suspension_reason": None,
        "suspended_at": None,
    })
    db.assets[asset["id"]] = asset
    core.recompute_energy_chain(asset)
    return response.created(db.serialize(asset))


@bp.get("/storage-assets/<asset_id>")
def read_asset(asset_id):
    middleware.any_role()
    asset = core.get_asset(asset_id)
    return response.ok(db.serialize(asset))


@bp.get("/storage-assets")
def list_assets():
    middleware.any_role()
    limit, offset = v.pagination()
    safety_state = v.query_enum("safety_state", SAFETY_STATES)
    market_state = v.query_enum("market_state", MARKET_STATES)

    rows = list(db.assets.values())
    if safety_state is not None:
        rows = [r for r in rows if r["safety_state"] == safety_state]
    if market_state is not None:
        rows = [r for r in rows if r["market_state"] == market_state]
    rows = core.newest_first(rows)
    page, total = core.paginate(rows, limit, offset)
    return response.ok_list([db.serialize(r) for r in page], limit, offset, total)


@bp.post("/storage-assets/<asset_id>/commission")
def commission_asset(asset_id):
    middleware.authorize("PlatformAdmin", "AssetManager")
    asset = core.get_asset(asset_id)

    if asset["market_state"] != "OFFLINE":
        raise ApiError(errors.ERR_ASSET_NOT_OFFLINE, 409,
                       "The asset's market_state is not OFFLINE.")
    if asset["safety_state"] != "NORMAL" or core.has_blocking_event(asset):
        raise ApiError(errors.ERR_ASSET_SAFETY_LOCKOUT, 409,
                       "The asset's safety posture forbids commissioning.")

    asset["market_state"] = "AVAILABLE"
    asset["suspension_reason"] = None
    asset["suspended_at"] = None
    db.touch(asset)
    return response.ok(db.serialize(asset))


@bp.post("/_clock/set_current_utc")
def set_clock():
    middleware.authorize("PlatformAdmin")
    body = v.json_body()
    _raw, parsed = v.timestamp(body, "current_utc")
    db.set_clock(parsed)
    return response.ok({})
