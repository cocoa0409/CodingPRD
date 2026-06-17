"""Park, weather, and the park-scoped inventory creation/listing endpoints."""
from flask import Blueprint

import errors
from db import db, new_id, add_common_fields, touch
from errors import ApiError
from middleware import authenticate, require_role
from response import success, list_success
from services import serialize
from services.common import (
    get_json_body, require_string, require_int, require_enum,
    optional_int, parse_pagination, paginate,
)
from services.lookup import get_park
from services.windows import recompute_open_window_count

bp = Blueprint("parks", __name__)

WEATHER_VALUES = {"CLEAR", "STORM_WATCH", "RAINED_OUT"}
CABANA_TIERS = {"STANDARD", "PREMIUM", "CABANA_SUITE"}


# ---- Park ----
@bp.route("/parks", methods=["POST"])
def create_park():
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    body = get_json_body()

    name = require_string(body, "name")
    total_gate_capacity = require_int(body, "total_gate_capacity", minimum=1)

    timezone = body.get("timezone")
    if timezone is None:
        timezone = "America/New_York"
    elif not isinstance(timezone, str) or not timezone.strip():
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "timezone must be a string")

    resident_zip_prefixes = body.get("resident_zip_prefixes")
    if resident_zip_prefixes is None:
        resident_zip_prefixes = []
    elif not isinstance(resident_zip_prefixes, list) or not all(
        isinstance(p, str) for p in resident_zip_prefixes
    ):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                       "resident_zip_prefixes must be a list of strings")

    rain_check_value_cents = optional_int(body, "rain_check_value_cents", 0, minimum=0)

    rec = {
        "id": new_id(),
        "name": name,
        "timezone": timezone,
        "total_gate_capacity": total_gate_capacity,
        "weather_status": "CLEAR",
        "resident_zip_prefixes": list(resident_zip_prefixes),
        "open_window_count": 0,
        "rain_check_value_cents": rain_check_value_cents,
    }
    add_common_fields(rec)
    db.parks[rec["id"]] = rec
    return success(serialize.park(rec), status=201)


@bp.route("/parks/<pid>", methods=["GET"])
def get_park_route(pid):
    _, role = authenticate()
    require_role(role, {"ParkManager", "GateAgent", "FinanceClerk", "Guest"})
    rec = get_park(pid)
    return success(serialize.park(rec))


@bp.route("/parks", methods=["GET"])
def list_parks():
    _, role = authenticate()
    require_role(role, {"ParkManager", "GateAgent", "FinanceClerk", "Guest"})
    limit, offset = parse_pagination()
    page, total = paginate(list(db.parks.values()), limit, offset)
    return list_success([serialize.park(r) for r in page], limit, offset, total)


@bp.route("/parks/<pid>/weather", methods=["POST"])
def set_weather(pid):
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    rec = get_park(pid)
    body = get_json_body()
    weather_status = require_enum(body, "weather_status", WEATHER_VALUES)
    rec["weather_status"] = weather_status
    touch(rec)
    return success(serialize.park(rec))


# ---- EntryWindow creation/listing under a park ----
@bp.route("/parks/<pid>/entry-windows", methods=["POST"])
def create_entry_window(pid):
    from services.common import parse_datetime
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    park = get_park(pid)
    body = get_json_body()
    if "starts_at" not in body or body["starts_at"] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Missing required field: starts_at")
    if "ends_at" not in body or body["ends_at"] is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Missing required field: ends_at")
    starts_dt = parse_datetime(body["starts_at"], "starts_at")
    ends_dt = parse_datetime(body["ends_at"], "ends_at")
    if not (starts_dt < ends_dt):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "starts_at must be strictly before ends_at")
    window_capacity = require_int(body, "window_capacity", minimum=1)

    rec = {
        "id": new_id(),
        "park_id": park["id"],
        "starts_at": body["starts_at"],
        "ends_at": body["ends_at"],
        "window_capacity": window_capacity,
        "reserved_count": 0,
        "admitted_count": 0,
        "status": "OPEN",
    }
    add_common_fields(rec)
    db.entry_windows[rec["id"]] = rec
    recompute_open_window_count(park)
    return success(serialize.entry_window(rec), status=201)


@bp.route("/parks/<pid>/entry-windows", methods=["GET"])
def list_entry_windows(pid):
    _, role = authenticate()
    require_role(role, {"ParkManager", "GateAgent", "Guest"})
    park = get_park(pid)
    limit, offset = parse_pagination()
    from flask import request
    status = request.args.get("status")
    rows = [w for w in db.entry_windows.values() if w["park_id"] == park["id"]]
    if status is not None:
        rows = [w for w in rows if w["status"] == status]
    page, total = paginate(rows, limit, offset)
    return list_success([serialize.entry_window(r) for r in page], limit, offset, total)


# ---- Cabana creation/listing under a park ----
@bp.route("/parks/<pid>/cabanas", methods=["POST"])
def create_cabana(pid):
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    park = get_park(pid)
    body = get_json_body()
    label = require_string(body, "label")
    tier = require_enum(body, "tier", CABANA_TIERS)
    daily_rate_cents = require_int(body, "daily_rate_cents", minimum=0)
    turnover_buffer_minutes = optional_int(body, "turnover_buffer_minutes", 30, minimum=0)

    rec = {
        "id": new_id(),
        "park_id": park["id"],
        "label": label,
        "tier": tier,
        "daily_rate_cents": daily_rate_cents,
        "turnover_buffer_minutes": turnover_buffer_minutes,
    }
    add_common_fields(rec)
    db.cabanas[rec["id"]] = rec
    return success(serialize.cabana(rec), status=201)


@bp.route("/parks/<pid>/cabanas", methods=["GET"])
def list_cabanas(pid):
    _, role = authenticate()
    require_role(role, {"ParkManager", "Guest"})
    park = get_park(pid)
    limit, offset = parse_pagination()
    from flask import request
    tier = request.args.get("tier")
    rows = [c for c in db.cabanas.values() if c["park_id"] == park["id"]]
    if tier is not None:
        rows = [c for c in rows if c["tier"] == tier]
    page, total = paginate(rows, limit, offset)
    return list_success([serialize.cabana(r) for r in page], limit, offset, total)


@bp.route("/cabanas/<cid>", methods=["GET"])
def get_cabana_route(cid):
    from services.lookup import get_cabana
    _, role = authenticate()
    require_role(role, {"ParkManager", "Guest"})
    rec = get_cabana(cid)
    return success(serialize.cabana(rec))


# ---- Locker creation/listing under a park ----
@bp.route("/parks/<pid>/lockers", methods=["POST"])
def create_locker(pid):
    _, role = authenticate()
    require_role(role, {"ParkManager"})
    park = get_park(pid)
    body = get_json_body()
    bank_code = require_string(body, "bank_code")
    hourly_rate_cents = require_int(body, "hourly_rate_cents", minimum=0)

    rec = {
        "id": new_id(),
        "park_id": park["id"],
        "bank_code": bank_code,
        "hourly_rate_cents": hourly_rate_cents,
    }
    add_common_fields(rec)
    db.lockers[rec["id"]] = rec
    return success(serialize.locker(rec), status=201)


@bp.route("/parks/<pid>/lockers", methods=["GET"])
def list_lockers(pid):
    _, role = authenticate()
    require_role(role, {"ParkManager", "Guest"})
    park = get_park(pid)
    limit, offset = parse_pagination()
    rows = [l for l in db.lockers.values() if l["park_id"] == park["id"]]
    page, total = paginate(rows, limit, offset)
    return list_success([serialize.locker(r) for r in page], limit, offset, total)


@bp.route("/lockers/<lid>", methods=["GET"])
def get_locker_route(lid):
    from services.lookup import get_locker
    _, role = authenticate()
    require_role(role, {"ParkManager", "Guest"})
    rec = get_locker(lid)
    return success(serialize.locker(rec))
