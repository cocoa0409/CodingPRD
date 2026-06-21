"""DemandForecast routes (PRD §3.10 demand forecasting)."""
import math
from datetime import timedelta

from flask import Blueprint, request

from db import db, parse_dt
from errors import err
from middleware import get_auth, require_roles, get_json_body
from response import object_response, array_response
from services import core

bp = Blueprint("forecasts", __name__)

LOOKBACK_DAYS = 30
ISSUANCE_WEIGHT = 0.70
HIRE_WEIGHT = 0.30


@bp.route("/demand-forecasts", methods=["POST"])
def compute_forecast():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    body = get_json_body()
    # Existence first (priority 3, PRD §2.10): body FKs left-to-right.
    core.resolve_body_fk(body, "location_id", db.locations)
    core.resolve_body_fk(body, "asset_type_id", db.asset_types)
    # Body well-formedness (priority 4).
    core.require_fields(body, ["location_id", "asset_type_id", "horizon_days"])
    location_id = core.require_str(body, "location_id")
    asset_type_id = core.require_str(body, "asset_type_id")
    horizon_days = core.require_int(body, "horizon_days", minimum=1)

    location = db.locations[location_id]

    # issuance_velocity: total quantity over RECEIVED ISSUANCE transfer orders
    # directed to this location within the last 30 days, divided by 30 (PRD §3.10).
    lookback_start = db.clock - timedelta(seconds=LOOKBACK_DAYS * core.DAY_SECONDS)
    issuance_qty = 0
    for o in db.transfer_orders.values():
        if o["status"] != "RECEIVED":
            continue
        if o["kind"] != "ISSUANCE":
            continue
        if o["to_location_id"] != location_id:
            continue
        received = parse_dt(o["received_at"]) if o["received_at"] else None
        if received is None:
            continue
        if lookback_start <= received <= db.clock:
            issuance_qty += o["quantity"]
    issuance_velocity = issuance_qty / LOOKBACK_DAYS

    # open_hire_runrate: count of assets currently ON_HIRE at this location for
    # this asset type, taken as a snapshot level (PRD §3.10).
    open_hire_runrate = 0
    for a in db.assets.values():
        if a["condition"] != "ON_HIRE":
            continue
        if a["asset_type_id"] != asset_type_id:
            continue
        hid = a["current_hire_id"]
        if hid is None:
            continue
        h = db.hires.get(hid)
        if h is not None and h["location_id"] == location_id:
            open_hire_runrate += 1

    # Blended per-day figure (PRD §3.10).
    blended_per_day = (ISSUANCE_WEIGHT * issuance_velocity
                       + HIRE_WEIGHT * (open_hire_runrate / LOOKBACK_DAYS))
    projected_demand = math.ceil(blended_per_day * horizon_days)

    # recommended_reposition = max(0, projected_demand - physical_balance) (PRD §3.10).
    core.recompute_physical_balance(location)
    recommended = max(0, projected_demand - location["physical_balance"])

    forecast = core.stamp_new({
        "location_id": location_id,
        "asset_type_id": asset_type_id,
        "horizon_days": horizon_days,
        "projected_demand": projected_demand,
        "recommended_reposition": recommended,
        "status": "COMPUTED",
    })
    db.demand_forecasts[forecast["id"]] = forecast
    return object_response(core.public(forecast), 201)


@bp.route("/demand-forecasts/<demand_forecast_id>", methods=["GET"])
def get_forecast(demand_forecast_id):
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    forecast = core.require(db.demand_forecasts, demand_forecast_id)
    return object_response(core.public(forecast), 200)


@bp.route("/demand-forecasts", methods=["GET"])
def list_forecasts():
    _, role = get_auth()
    require_roles(role, {"PoolAdmin", "PoolOperator", "Participant"})
    items = list(db.demand_forecasts.values())
    for field in ("location_id", "asset_type_id"):
        val = request.args.get(field)
        if val is not None:
            items = [f for f in items if f[field] == val]
    data, limit, offset, total = core.paginate(items, request.args)
    return array_response(data, limit, offset, total, 200)
