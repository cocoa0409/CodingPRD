"""FeedStation endpoints + telemetry readings."""

from flask import Blueprint, g

import errors
from calc import feed_rate_setpoint, accepted_design_of, recompute_station
from db import db, create_entity, touch, now
from helpers import list_response, account_of_station, account_of_reading, query_filter
from response import success_object, success_list
from serializers import feed_station as ser, telemetry_reading as ser_reading
from validate import (get_body, validate_shape, resolve, resolve_body_fk,
                      check_cc_ownership, paginate)

bp = Blueprint("feed_stations", __name__)

FEED_MODES = ("CONTINUOUS", "SHOT_FEED")


@bp.route("/wt/feed-stations", methods=["POST"])
def create_station():
    body = get_body()
    # Tier 4 body FKs in declared input order: asset_id, then product_id.
    asset = resolve_body_fk(body, "asset_id", "assets")
    product = resolve_body_fk(body, "product_id", "products")
    vals = validate_shape(body, [
        ("asset_id", "str", True),
        ("product_id", "str", True),
        ("capacity_cap_ml_per_min", "num", True),
        ("feed_mode", "str", False, FEED_MODES),
    ])
    # Tier 10
    if vals["capacity_cap_ml_per_min"] <= 0:
        raise errors.field_constraint("capacity_cap_ml_per_min must be > 0")
    # Tier 13 referential integrity: product must be LISTED.
    if product["status"] == "DELISTED":
        raise errors.ApiError(errors.ERR_PRODUCT_DELISTED, 409,
                              "Cannot create a feed station referencing a DELISTED product")
    ent = create_entity("feed_stations", {
        "asset_id": asset["id"],
        "product_id": product["id"],
        "feed_mode": vals["feed_mode"] or "CONTINUOUS",
        "capacity_cap_ml_per_min": vals["capacity_cap_ml_per_min"],
        "setpoint_ml_per_min": 0,
        "inventory_gal": 0,
        "consumption_rate_gal_per_day": 0,
        "projected_depletion_at": None,
        "last_telemetry_at": None,
        "status": "OFFLINE",
    })
    # Setpoint is computed at creation when an ACCEPTED design exists.
    design = accepted_design_of(asset["id"])
    if design is not None:
        ent["setpoint_ml_per_min"] = feed_rate_setpoint(asset, design, product, ent)
    return success_object(ser(ent), 201)


@bp.route("/wt/feed-stations", methods=["GET"])
def list_stations():
    user = (g.role, g.user_id)
    items = list(db["feed_stations"].values())
    asset_id = query_filter("asset_id")
    if asset_id is not None:
        items = [s for s in items if s["asset_id"] == asset_id]
    product_id = query_filter("product_id")
    if product_id is not None:
        items = [s for s in items if s["product_id"] == product_id]
    return list_response(items, ser, account_of_station, user)


@bp.route("/wt/feed-stations/<stationId>", methods=["GET"])
def get_station(stationId):
    ent = db["feed_stations"].get(stationId)
    if ent is not None:
        check_cc_ownership(g.user_id, g.role, account_of_station(ent))
    ent = resolve("feed_stations", stationId)
    return success_object(ser(ent), 200)


@bp.route("/wt/feed-stations/<stationId>/bring-online", methods=["POST"])
def bring_online(stationId):
    ent = resolve("feed_stations", stationId)
    get_body()
    if ent["status"] not in ("OFFLINE", "LOCKED_OUT"):
        raise errors.invalid_state("Station must be OFFLINE or LOCKED_OUT to bring online")
    asset = db["assets"].get(ent["asset_id"])
    if asset is not None and asset["status"] == "DECOMMISSIONED":
        raise errors.ApiError(errors.ERR_ASSET_DECOMMISSIONED, 409,
                              "Station's asset is DECOMMISSIONED")
    ent["status"] = "ONLINE"
    touch(ent)
    return success_object(ser(ent), 200)


@bp.route("/wt/feed-stations/<stationId>/lockout", methods=["POST"])
def lockout(stationId):
    ent = resolve("feed_stations", stationId)
    get_body()
    if ent["status"] != "ONLINE":
        raise errors.invalid_state("Station must be ONLINE to lock out")
    ent["status"] = "LOCKED_OUT"
    touch(ent)
    return success_object(ser(ent), 200)


@bp.route("/wt/feed-stations/<stationId>/telemetry", methods=["POST"])
def post_telemetry(stationId):
    station = resolve("feed_stations", stationId)
    body = get_body()
    vals = validate_shape(body, [
        ("recorded_at", "iso", True),
        ("feed_pulses", "int", True),
        ("ml_per_pulse", "num", True),
        ("level_gal", "num", True),
    ])
    # Tier 6: station must be ONLINE.
    if station["status"] != "ONLINE":
        raise errors.invalid_state("Station must be ONLINE to accept telemetry")
    # Tier 10 field constraints.
    if vals["feed_pulses"] < 0:
        raise errors.field_constraint("feed_pulses must be >= 0")
    if vals["ml_per_pulse"] <= 0:
        raise errors.field_constraint("ml_per_pulse must be > 0")
    if vals["level_gal"] < 0:
        raise errors.field_constraint("level_gal must be >= 0")
    # Tier 11 temporal: recorded_at must not be later than the current clock.
    if vals["recorded_at"] > now():
        raise errors.ApiError(errors.ERR_TELEMETRY_FUTURE, 422,
                              "Telemetry recorded_at is later than the current clock")
    ent = create_entity("telemetry_readings", {
        "station_id": station["id"],
        "recorded_at": vals["recorded_at"],
        "feed_pulses": vals["feed_pulses"],
        "ml_per_pulse": vals["ml_per_pulse"],
        "level_gal": vals["level_gal"],
    }, common=False)
    # Mutate the station: inventory decremented by dosed volume (via full
    # reconciliation), rate and projection recomputed, last_telemetry_at set.
    recompute_station(station, bump=False)
    if station["last_telemetry_at"] != vals["recorded_at"]:
        station["last_telemetry_at"] = vals["recorded_at"]
    touch(station)
    return success_object(ser_reading(ent), 201)


@bp.route("/wt/feed-stations/<stationId>/telemetry", methods=["GET"])
def list_telemetry(stationId):
    station = db["feed_stations"].get(stationId)
    if station is not None:
        check_cc_ownership(g.user_id, g.role, account_of_station(station))
    station = resolve("feed_stations", stationId)
    # Ordered recorded_at ASC, created_at ASC (never id).
    items = [r for r in db["telemetry_readings"].values() if r["station_id"] == station["id"]]
    items.sort(key=lambda r: (r["recorded_at"], r["created_at"], r["_seq"]))
    page, limit, offset, total = paginate(items)
    return success_list([ser_reading(r) for r in page], limit, offset, total)
