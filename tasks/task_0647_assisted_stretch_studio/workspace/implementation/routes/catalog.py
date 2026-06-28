"""Catalog routes: Location, Flexologist, Table, Service (PRD §3.1)."""
from flask import Blueprint

from db import store
from errors import err, ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE
from middleware import authenticate, require_role
from response import success, success_list
from util import (
    get_json_body, require_str, opt_str, opt_int, opt_number, opt_bool,
    require_int, require_number, require_enum, parse_pagination, paginate,
)
from services.common import make_full, bump
from services import serialize

bp = Blueprint("catalog", __name__)

ALL_ROLES = ["StudioManager", "FrontDesk", "Member", "Flexologist"]


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------
@bp.route("/locations", methods=["POST"])
def create_location():
    p = authenticate()
    require_role(p, ["StudioManager"])
    body = get_json_body()
    name = require_str(body, "name")
    timezone = opt_str(body, "timezone", "UTC")
    open_min = opt_int(body, "open_minute_of_day", 540, minimum=0, maximum=1439)
    close_min = opt_int(body, "close_minute_of_day", 1260, minimum=1, maximum=1440)
    if not (open_min < close_min <= 1440):
        raise err(ERR_VALIDATION, "open_minute_of_day < close_minute_of_day <= 1440 required.")
    buffer_min = opt_int(body, "flexologist_buffer_minutes", 15, minimum=0)
    no_show_fee = opt_int(body, "no_show_fee_cents", 5000, minimum=0)
    late_pct = opt_number(body, "late_cancel_pct", 0.50, minimum=0, maximum=1)
    cancel_window = opt_int(body, "cancel_window_hours", 12, minimum=0)
    rec = make_full({
        "name": name,
        "timezone": timezone,
        "open_minute_of_day": open_min,
        "close_minute_of_day": close_min,
        "flexologist_buffer_minutes": buffer_min,
        "no_show_fee_cents": no_show_fee,
        "late_cancel_pct": late_pct,
        "cancel_window_hours": cancel_window,
        "status": "OPEN",
    })
    store.locations[rec["id"]] = rec
    return success(serialize.location_view(rec), 201)


@bp.route("/locations", methods=["GET"])
def list_locations():
    p = authenticate()
    require_role(p, ALL_ROLES)
    limit, offset = parse_pagination()
    status = _qs("status")
    items = [r for r in store.locations.values()
             if status is None or r["status"] == status]
    window, total = paginate(items, limit, offset)
    return success_list([serialize.location_view(r) for r in window], limit, offset, total)


@bp.route("/locations/<lid>", methods=["GET"])
def get_location(lid):
    p = authenticate()
    require_role(p, ALL_ROLES)
    rec = store.locations.get(lid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Location not found.")
    return success(serialize.location_view(rec), 200)


@bp.route("/locations/<lid>/close", methods=["POST"])
def close_location(lid):
    p = authenticate()
    require_role(p, ["StudioManager"])
    rec = store.locations.get(lid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Location not found.")
    rec["status"] = "CLOSED"
    bump(rec)
    return success(serialize.location_view(rec), 200)


# ---------------------------------------------------------------------------
# Flexologists
# ---------------------------------------------------------------------------
@bp.route("/flexologists", methods=["POST"])
def create_flexologist():
    p = authenticate()
    require_role(p, ["StudioManager"])
    body = get_json_body()
    location_id = require_str(body, "location_id")
    full_name = require_str(body, "full_name")
    certified = opt_bool(body, "certified_intro", False)
    if location_id not in store.locations:
        raise err(ERR_NOT_FOUND, "Location not found.")
    rec = make_full({
        "location_id": location_id,
        "full_name": full_name,
        "certified_intro": certified,
        "status": "ACTIVE",
    })
    store.flexologists[rec["id"]] = rec
    return success(serialize.flexologist_view(rec), 201)


@bp.route("/flexologists", methods=["GET"])
def list_flexologists():
    p = authenticate()
    require_role(p, ["StudioManager", "FrontDesk", "Member"])
    limit, offset = parse_pagination()
    location_id = _qs("location_id")
    status = _qs("status")
    items = [r for r in store.flexologists.values()
             if (location_id is None or r["location_id"] == location_id)
             and (status is None or r["status"] == status)]
    window, total = paginate(items, limit, offset)
    return success_list([serialize.flexologist_view(r) for r in window], limit, offset, total)


@bp.route("/flexologists/<fid>", methods=["GET"])
def get_flexologist(fid):
    p = authenticate()
    require_role(p, ALL_ROLES)
    rec = store.flexologists.get(fid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Flexologist not found.")
    return success(serialize.flexologist_view(rec), 200)


@bp.route("/flexologists/<fid>/deactivate", methods=["POST"])
def deactivate_flexologist(fid):
    p = authenticate()
    require_role(p, ["StudioManager"])
    rec = store.flexologists.get(fid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Flexologist not found.")
    rec["status"] = "INACTIVE"
    bump(rec)
    return success(serialize.flexologist_view(rec), 200)


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
@bp.route("/tables", methods=["POST"])
def create_table():
    p = authenticate()
    require_role(p, ["StudioManager"])
    body = get_json_body()
    location_id = require_str(body, "location_id")
    label = require_str(body, "label")
    if location_id not in store.locations:
        raise err(ERR_NOT_FOUND, "Location not found.")
    rec = make_full({
        "location_id": location_id,
        "label": label,
        "status": "ACTIVE",
    })
    store.tables[rec["id"]] = rec
    return success(serialize.table_view(rec), 201)


@bp.route("/tables", methods=["GET"])
def list_tables():
    p = authenticate()
    require_role(p, ["StudioManager", "FrontDesk", "Member"])
    limit, offset = parse_pagination()
    location_id = _qs("location_id")
    status = _qs("status")
    items = [r for r in store.tables.values()
             if (location_id is None or r["location_id"] == location_id)
             and (status is None or r["status"] == status)]
    window, total = paginate(items, limit, offset)
    return success_list([serialize.table_view(r) for r in window], limit, offset, total)


@bp.route("/tables/<tid>", methods=["GET"])
def get_table(tid):
    p = authenticate()
    require_role(p, ALL_ROLES)
    rec = store.tables.get(tid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Table not found.")
    return success(serialize.table_view(rec), 200)


@bp.route("/tables/<tid>/take-out-of-service", methods=["POST"])
def take_table_oos(tid):
    p = authenticate()
    require_role(p, ["StudioManager"])
    rec = store.tables.get(tid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Table not found.")
    rec["status"] = "OUT_OF_SERVICE"
    bump(rec)
    return success(serialize.table_view(rec), 200)


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------
@bp.route("/services", methods=["POST"])
def create_service():
    p = authenticate()
    require_role(p, ["StudioManager"])
    body = get_json_body()
    location_id = require_str(body, "location_id")
    name = require_str(body, "name")
    kind = require_enum(body, "kind", {"ASSISTED_STRETCH", "RECOVERY", "INTRO"})
    duration = require_int(body, "duration_minutes", minimum=1)
    credit_cost = require_int(body, "credit_cost", minimum=0)
    list_price = require_int(body, "list_price_cents", minimum=0)
    if location_id not in store.locations:
        raise err(ERR_NOT_FOUND, "Location not found.")
    rec = make_full({
        "location_id": location_id,
        "name": name,
        "kind": kind,
        "duration_minutes": duration,
        "credit_cost": credit_cost,
        "list_price_cents": list_price,
        "status": "ACTIVE",
    })
    store.services[rec["id"]] = rec
    return success(serialize.service_view(rec), 201)


@bp.route("/services", methods=["GET"])
def list_services():
    p = authenticate()
    require_role(p, ["StudioManager", "FrontDesk", "Member"])
    limit, offset = parse_pagination()
    location_id = _qs("location_id")
    kind = _qs("kind")
    status = _qs("status")
    items = [r for r in store.services.values()
             if (location_id is None or r["location_id"] == location_id)
             and (kind is None or r["kind"] == kind)
             and (status is None or r["status"] == status)]
    window, total = paginate(items, limit, offset)
    return success_list([serialize.service_view(r) for r in window], limit, offset, total)


@bp.route("/services/<sid>", methods=["GET"])
def get_service(sid):
    p = authenticate()
    require_role(p, ALL_ROLES)
    rec = store.services.get(sid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Service not found.")
    return success(serialize.service_view(rec), 200)


@bp.route("/services/<sid>/retire", methods=["POST"])
def retire_service(sid):
    p = authenticate()
    require_role(p, ["StudioManager"])
    rec = store.services.get(sid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Service not found.")
    rec["status"] = "RETIRED"
    bump(rec)
    return success(serialize.service_view(rec), 200)


def _qs(name):
    from flask import request
    v = request.args.get(name)
    if v is None or v == "":
        return None
    return v
