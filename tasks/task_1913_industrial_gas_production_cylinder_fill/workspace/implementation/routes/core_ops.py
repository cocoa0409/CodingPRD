"""Clock, Plant, StorageTank, TelemetryReading endpoints."""
from flask import Blueprint

from constants import PLANT_STATUSES, PRODUCTS, READING_SOURCES, TANK_STATUSES
from db import store
from errors import (
    ERR_FILL_LOT_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_TELEMETRY_FUTURE_DATED,
    ApiError,
    bad_enum,
    bad_request,
    not_found,
)
from middleware import (
    ANY_ROLE,
    get_body,
    locked,
    req_enum,
    req_int,
    req_num,
    req_str,
    require_roles,
)
from response import success
from routes.listing import list_response
from services import calc
from services.ops import (
    auto_replenishment_if_low,
    base_record,
    installation_out,
    plant_out,
    post_reading,
    reading_out,
    tank_out,
)
from util import (
    clock_now,
    dec,
    fmt_instant,
    is_int,
    parse_instant,
    round2,
    touch,
)

bp = Blueprint("core_ops", __name__)


# ---------------- logical clock ----------------

@bp.post("/api/_clock/set_current_utc")
@locked
def set_clock():
    require_roles("PlantManager")
    body = get_body()
    raw = body.get("to_iso8601")
    dt = parse_instant(raw)
    if dt is None:
        bad_request("to_iso8601 must be a valid ISO 8601 instant")
    store.clock = dt
    return success({"current_utc": fmt_instant(store.clock)})


# ---------------- plants ----------------

@bp.post("/api/plants")
@locked
def create_plant():
    require_roles("PlantManager")
    body = get_body()
    name = req_str(body, "plant_name")
    p = base_record()
    p.update({"plant_name": name, "status": "OPERATING"})
    store.plants[p["id"]] = p
    return success(plant_out(p), status=201)


@bp.get("/api/plants")
@locked
def list_plants():
    require_roles(*ANY_ROLE)
    return list_response(store.plants.values(), plant_out, [("status", "status")])


@bp.get("/api/plants/<plantId>")
@locked
def get_plant(plantId):
    require_roles(*ANY_ROLE)
    p = store.plants.get(plantId)
    if p is None:
        not_found("plant not found")
    return success(plant_out(p))


@bp.post("/api/plants/<plantId>/set-status")
@locked
def plant_set_status(plantId):
    require_roles("PlantManager")
    body = get_body()
    target = req_enum(body, "target_status", PLANT_STATUSES)
    p = store.plants.get(plantId)
    if p is None:
        not_found("plant not found")
    allowed = {"OPERATING": {"MAINTENANCE_SHUTDOWN"}, "MAINTENANCE_SHUTDOWN": {"OPERATING"}}
    if target not in allowed[p["status"]]:
        bad_request("target_status unreachable from current plant status")
    p["status"] = target
    touch(p)
    return success(plant_out(p))


# ---------------- storage tanks ----------------

@bp.post("/api/tanks")
@locked
def create_tank():
    uid, _ = require_roles("PlantManager")
    body = get_body()
    plant_id = req_str(body, "plant_id")
    product = req_enum(body, "product_code", PRODUCTS)
    capacity = req_int(body, "capacity_liters")
    initial = req_int(body, "initial_level_liters")
    reorder = req_int(body, "reorder_point_liters")
    if capacity <= 0:
        bad_request("capacity_liters must be > 0")
    if initial < 0 or initial > capacity:
        bad_request("initial_level_liters must be within [0, capacity_liters]")
    if reorder < 0 or reorder > capacity:
        bad_request("reorder_point_liters must be within [0, capacity_liters]")
    plant = store.plants.get(plant_id)
    if plant is None:
        not_found("plant not found")
    t = base_record()
    t.update(
        {
            "plant_id": plant_id,
            "product_code": product,
            "capacity_liters": capacity,
            "initial_level_liters": initial,
            "reorder_point_liters": reorder,
            "reserved_liters": dec(0),
            "drawn_liters": dec(0),
            "status": "IN_SERVICE",
        }
    )
    store.tanks[t["id"]] = t
    post_reading(t["id"], None, dec(initial), clock_now(), "INITIAL_LOAD", uid)
    return success(tank_out(t), status=201)


@bp.get("/api/tanks")
@locked
def list_tanks():
    require_roles(*ANY_ROLE)
    return list_response(
        store.tanks.values(),
        tank_out,
        [("plant_id", "plant_id"), ("status", "status"), ("product_code", "product_code")],
    )


@bp.get("/api/tanks/<tankId>")
@locked
def get_tank(tankId):
    require_roles(*ANY_ROLE)
    t = store.tanks.get(tankId)
    if t is None:
        not_found("tank not found")
    return success(tank_out(t))


@bp.patch("/api/tanks/<tankId>")
@locked
def patch_tank(tankId):
    require_roles("PlantManager")
    body = get_body()
    expected = body.get("expected_tank_version")
    if expected is None or not is_int(expected):
        bad_request("expected_tank_version is required and must be an integer")
    reorder = body.get("reorder_point_liters")
    if reorder is not None and not is_int(reorder):
        bad_request("reorder_point_liters must be an integer")
    t = store.tanks.get(tankId)
    if t is None:
        not_found("tank not found")
    if reorder is not None and (reorder < 0 or reorder > t["capacity_liters"]):
        bad_request("reorder_point_liters must be within [0, capacity_liters]")
    if expected != t["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "tank version is stale")
    if reorder is not None:
        t["reorder_point_liters"] = reorder
    touch(t)
    return success(tank_out(t))


@bp.post("/api/tanks/<tankId>/set-status")
@locked
def tank_set_status(tankId):
    require_roles("PlantManager")
    body = get_body()
    target = req_enum(body, "target_status", TANK_STATUSES)
    t = store.tanks.get(tankId)
    if t is None:
        not_found("tank not found")
    allowed = {
        "IN_SERVICE": {"MAINTENANCE", "QUARANTINED"},
        "MAINTENANCE": {"IN_SERVICE"},
        "QUARANTINED": {"IN_SERVICE"},
    }
    if target not in allowed[t["status"]]:
        bad_request("target_status unreachable from current tank status")
    if t["status"] == "IN_SERVICE":
        for lot in store.fill_lots.values():
            if lot["tank_id"] == t["id"] and lot["status"] in ("FILLING", "AWAITING_ANALYSIS"):
                raise ApiError(
                    ERR_FILL_LOT_INVALID_STATE,
                    409,
                    "a fill lot on this tank is FILLING or AWAITING_ANALYSIS",
                )
    t["status"] = target
    touch(t)
    return success(tank_out(t))


# ---------------- telemetry readings ----------------

@bp.post("/api/telemetry-readings")
@locked
def create_reading():
    uid, _ = require_roles("ProductionOperator", "LogisticsCoordinator")
    body = get_body()
    tank_id = body.get("tank_id")
    installation_id = body.get("installation_id")
    if tank_id is not None and not isinstance(tank_id, str):
        bad_request("tank_id must be a string")
    if installation_id is not None and not isinstance(installation_id, str):
        bad_request("installation_id must be a string")
    if (tank_id is None) == (installation_id is None):
        bad_request("exactly one of tank_id / installation_id must be present")
    level = req_num(body, "measured_level_liters")
    if dec(level) < 0:
        bad_request("measured_level_liters must be >= 0")
    measured_at = parse_instant(body.get("measured_at"))
    if measured_at is None:
        bad_request("measured_at must be a valid ISO 8601 instant")
    source = req_enum(body, "source", READING_SOURCES)

    if tank_id is not None:
        owner = store.tanks.get(tank_id)
        if owner is None:
            not_found("tank not found")
    else:
        owner = store.installations.get(installation_id)
        if owner is None:
            not_found("installation not found")
    if dec(level) > dec(owner["capacity_liters"]):
        bad_request("measured_level_liters exceeds owner capacity")
    if measured_at > clock_now():
        raise ApiError(ERR_TELEMETRY_FUTURE_DATED, 422, "measured_at is later than the logical clock")

    r = post_reading(tank_id, installation_id, round2(level), measured_at, source, uid)
    if tank_id is not None:
        # A new reading that becomes the governing one resets drawn_liters to 0
        # (the physical draw is now reflected in the measurement).
        gov = calc.governing_reading("tank_id", tank_id)
        if gov is not None and gov["id"] == r["id"] and owner["drawn_liters"] != 0:
            owner["drawn_liters"] = dec(0)
    else:
        auto_replenishment_if_low(owner, set())
    return success(reading_out(r), status=201)


@bp.get("/api/telemetry-readings")
@locked
def list_readings():
    require_roles(*ANY_ROLE)
    return list_response(
        store.readings.values(),
        reading_out,
        [("tank_id", "tank_id"), ("installation_id", "installation_id"), ("source", "source")],
    )


@bp.get("/api/telemetry-readings/<readingId>")
@locked
def get_reading(readingId):
    require_roles(*ANY_ROLE)
    r = store.readings.get(readingId)
    if r is None:
        not_found("reading not found")
    return success(reading_out(r))
