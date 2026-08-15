"""SystemAsset endpoints + blowdown events + water-savings report."""

from flask import Blueprint, g

import errors
from calc import (recompute_posture, blowdown_calc, BASELINE_COC, round_places)
from db import db, create_entity, touch, now
from helpers import list_response, account_of_asset, account_of_blowdown, query_filter
from response import success_object
from serializers import asset as ser, blowdown_event as ser_blowdown
from validate import (get_body, validate_shape, resolve, resolve_body_fk,
                      check_cc_ownership, paginate)
from response import success_list

bp = Blueprint("assets", __name__)

ASSET_TYPES = ("COOLING_TOWER", "BOILER", "CLOSED_LOOP")
METALLURGIES = ("MILD_STEEL", "COPPER_ALLOY", "STAINLESS", "GALVANIZED")


@bp.route("/wt/assets", methods=["POST"])
def create_asset():
    body = get_body()
    # Tier 4: body FK account_id first (declared input order).
    account = resolve_body_fk(body, "account_id", "accounts")
    vals = validate_shape(body, [
        ("account_id", "str", True),
        ("asset_tag", "str", True),
        ("asset_type", "str", True, ASSET_TYPES),
        ("recirculation_rate_gpm", "num", True),
        ("system_volume_gal", "num", True),
        ("metallurgy", "str", True, METALLURGIES),
        ("evaporation_factor", "num", False),
        ("drift_factor", "num", False),
    ])
    # Tier 10: field constraints.
    if vals["recirculation_rate_gpm"] <= 0:
        raise errors.field_constraint("recirculation_rate_gpm must be > 0")
    if vals["system_volume_gal"] <= 0:
        raise errors.field_constraint("system_volume_gal must be > 0")
    for existing in db["assets"].values():
        if existing["account_id"] == account["id"] and existing["asset_tag"] == vals["asset_tag"]:
            raise errors.field_constraint("asset_tag must be unique per account")
    ent = create_entity("assets", {
        "account_id": account["id"],
        "asset_tag": vals["asset_tag"],
        "asset_type": vals["asset_type"],
        "recirculation_rate_gpm": vals["recirculation_rate_gpm"],
        "system_volume_gal": vals["system_volume_gal"],
        "metallurgy": vals["metallurgy"],
        "evaporation_factor": vals["evaporation_factor"] if vals["evaporation_factor"] is not None else 0.0085,
        "drift_factor": vals["drift_factor"] if vals["drift_factor"] is not None else 0.0002,
        "target_coc": 3.0,
        "consecutive_out_of_range_count": 0,
        "posture": "COMPLIANT",
        "status": "COMMISSIONING",
    })
    return success_object(ser(ent), 201)


@bp.route("/wt/assets", methods=["GET"])
def list_assets():
    user = (g.role, g.user_id)
    items = list(db["assets"].values())
    account_id = query_filter("account_id")
    if account_id is not None:
        items = [a for a in items if a["account_id"] == account_id]
    status = query_filter("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_response(items, ser, account_of_asset, user)


@bp.route("/wt/assets/<assetId>", methods=["GET"])
def get_asset(assetId):
    ent = db["assets"].get(assetId)
    if ent is not None:
        check_cc_ownership(g.user_id, g.role, ent["account_id"])
    ent = resolve("assets", assetId)
    return success_object(ser(ent), 200)


@bp.route("/wt/assets/<assetId>/commission", methods=["POST"])
def commission_asset(assetId):
    ent = resolve("assets", assetId)
    if ent["status"] != "COMMISSIONING":
        raise errors.invalid_state("Asset must be COMMISSIONING to commission")
    if not any(d["asset_id"] == ent["id"] and d["status"] == "ACCEPTED"
               for d in db["program_designs"].values()):
        raise errors.ApiError(errors.ERR_NO_ACCEPTED_PROGRAM, 409,
                              "Commission requires an ACCEPTED program design")
    if not any(s["asset_id"] == ent["id"] and s["status"] == "ONLINE"
               for s in db["feed_stations"].values()):
        raise errors.ApiError(errors.ERR_NO_ONLINE_FEED_STATION, 409,
                              "Commission requires an ONLINE feed station")
    ent["status"] = "IN_SERVICE"
    touch(ent)
    recompute_posture(ent)
    return success_object(ser(ent), 200)


@bp.route("/wt/assets/<assetId>/decommission", methods=["POST"])
def decommission_asset(assetId):
    ent = resolve("assets", assetId)
    if ent["status"] != "IN_SERVICE":
        raise errors.invalid_state("Asset must be IN_SERVICE to decommission")
    rack_ids = [r["id"] for r in db["coupon_racks"].values() if r["asset_id"] == ent["id"]]
    if any(c["rack_id"] in rack_ids and c["status"] == "INSTALLED"
           for c in db["corrosion_coupons"].values()):
        raise errors.ApiError(errors.ERR_COUPONS_STILL_INSTALLED, 409,
                              "Decommission blocked by INSTALLED coupons")
    if any(s["asset_id"] == ent["id"] and s["status"] in ("SCHEDULED", "ARRIVED")
           for s in db["route_stops"].values()):
        raise errors.ApiError(errors.ERR_OPEN_ROUTE_STOPS, 409,
                              "Decommission blocked by open route stops")
    ent["status"] = "DECOMMISSIONED"
    touch(ent)
    for station in db["feed_stations"].values():
        if station["asset_id"] == ent["id"] and station["status"] != "LOCKED_OUT":
            station["status"] = "LOCKED_OUT"
            touch(station)
    for plan in db["legionella_plans"].values():
        if plan["asset_id"] == ent["id"] and plan["status"] != "SUSPENDED":
            plan["status"] = "SUSPENDED"
            touch(plan)
    recompute_posture(ent)
    return success_object(ser(ent), 200)


# ---------------------------------------------------------------------------
# Blowdown events
# ---------------------------------------------------------------------------

def _blowdowns_of(asset_id):
    evts = [e for e in db["blowdown_events"].values() if e["asset_id"] == asset_id]
    evts.sort(key=lambda e: (e["occurred_at"], e["_seq"]))
    return evts


@bp.route("/wt/assets/<assetId>/blowdown-events", methods=["POST"])
def create_blowdown(assetId):
    asset = db["assets"].get(assetId)
    if asset is None:
        raise errors.not_found()
    body = get_body()
    vals = validate_shape(body, [
        ("occurred_at", "iso", True),
        ("blowdown_gal", "num", True),
        ("makeup_gal", "num", True),
    ])
    # Tier 10
    if vals["blowdown_gal"] <= 0:
        raise errors.field_constraint("blowdown_gal must be > 0")
    if vals["makeup_gal"] <= 0:
        raise errors.field_constraint("makeup_gal must be > 0")
    # Tier 11: occurred_at <= clock and strictly after previous event.
    occurred_at = vals["occurred_at"]
    previous = _blowdowns_of(asset["id"])
    prev_ts = previous[-1]["occurred_at"] if previous else asset["created_at"]
    if occurred_at > now():
        raise errors.ApiError(errors.ERR_NON_MONOTONIC_EVENT, 422,
                              "occurred_at must not exceed the current clock")
    if previous and occurred_at <= previous[-1]["occurred_at"]:
        raise errors.ApiError(errors.ERR_NON_MONOTONIC_EVENT, 422,
                              "occurred_at must be strictly after the previous event")
    calc = blowdown_calc(asset, prev_ts, occurred_at,
                         vals["blowdown_gal"], vals["makeup_gal"])
    ent = create_entity("blowdown_events", {
        "asset_id": asset["id"],
        "occurred_at": occurred_at,
        "blowdown_gal": vals["blowdown_gal"],
        "makeup_gal": vals["makeup_gal"],
        "evaporation_gal": calc["evaporation_gal"],
        "balance_residual_gal": calc["balance_residual_gal"],
    }, common=False)
    return success_object(ser_blowdown(ent), 201)


@bp.route("/wt/assets/<assetId>/blowdown-events", methods=["GET"])
def list_blowdowns(assetId):
    asset = db["assets"].get(assetId)
    if asset is not None:
        check_cc_ownership(g.user_id, g.role, asset["account_id"])
    asset = resolve("assets", assetId)
    items = _blowdowns_of(asset["id"])  # occurred_at ASC
    role, user_id = g.role, g.user_id
    if role == "CustomerContact":
        items = [e for e in items if account_of_blowdown(e) == user_id]
    page, limit, offset, total = paginate(items)
    return success_list([ser_blowdown(e) for e in page], limit, offset, total)


@bp.route("/wt/assets/<assetId>/water-savings", methods=["GET"])
def water_savings(assetId):
    asset = db["assets"].get(assetId)
    if asset is not None:
        check_cc_ownership(g.user_id, g.role, asset["account_id"])
    asset = resolve("assets", assetId)
    events = _blowdowns_of(asset["id"])
    rows = []
    prev_ts = asset["created_at"]
    total_saved = 0.0
    total_baseline = 0.0
    total_actual = 0.0
    for e in events:
        c = blowdown_calc(asset, prev_ts, e["occurred_at"], e["blowdown_gal"], e["makeup_gal"])
        rows.append({
            "event_id": e["id"],
            "occurred_at": e["occurred_at"],
            "evaporation_gal": c["evaporation_gal"],
            "achieved_coc": c["achieved_coc"],
            "saved_gal": c["saved_gal"],
        })
        total_saved += c["saved_gal"]
        total_baseline += round_places(c["baseline_blowdown_gal"], 2)
        total_actual += e["blowdown_gal"]
        prev_ts = e["occurred_at"]
    from db import fmt_ts
    for row, e in zip(rows, events):
        row["occurred_at"] = fmt_ts(e["occurred_at"])
    return success_object({
        "events": rows,
        "total_saved_gal": round_places(total_saved, 2),
        "baseline_blowdown_gal": round_places(total_baseline, 2),
        "actual_blowdown_gal": round_places(total_actual, 2),
        "event_count": len(events),
    }, 200)
