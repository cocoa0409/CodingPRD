"""Plants, stock-units, care-log."""
from flask import Blueprint, request
from clock import iso_now, parse_iso
from db import DB
from errors import (
    not_found, invalid_request, invalid_state, stale_version,
    ApiError, ERR_STOCK_UNIT_UNHEALTHY, ERR_INVALID_REQUEST,
)
from middleware import (
    auth_context, require_role, require_json,
    parse_pagination, sort_by_created, paginate,
)
from response import ok, created, ok_list
from services.common import stamp_common, bump
from services.validation import require_fields, require_enum, require_int, require_string
from services.inventory import recompute_available_count

bp = Blueprint("plants", __name__)

LIGHT_TAGS = {"LOW", "MEDIUM", "BRIGHT_INDIRECT", "DIRECT"}
CARE_TAGS = {"EASY", "MODERATE", "EXPERT"}
WEIGHT_CLASSES = {"LIGHT", "STANDARD", "HEAVY"}
HEALTH_STATUSES = {"HEALTHY", "RECOVERING", "DECLINING", "DEAD"}
SALE_STATUSES = {"FOR_SALE", "RESERVED", "SOLD", "SHRINK", "RETURNED"}
SHRINK_REASONS = {"NONE", "MORTALITY", "DAMAGED", "EXPIRED_HOLD", "WARRANTY_RETURN"}
ENTRY_TYPES = {"WATER", "LIGHT_CHECK", "PRUNE", "REPOT", "OBSERVATION", "SHRINK_DECLARE"}


@bp.post("/plants")
def create_plant():
    role, _ = auth_context()
    require_role(role, {"Manager"})
    payload = require_json()
    require_fields(payload, ["name", "light_tag", "care_tag", "weight_class", "unit_price_cents", "warranty_days"])
    require_enum(payload["light_tag"], LIGHT_TAGS, "light_tag")
    require_enum(payload["care_tag"], CARE_TAGS, "care_tag")
    require_enum(payload["weight_class"], WEIGHT_CLASSES, "weight_class")
    unit_price = require_int(payload, "unit_price_cents", minimum=100)
    warranty_days = require_int(payload, "warranty_days", minimum=0)
    name = require_string(payload, "name")
    entity = {
        **stamp_common(full=True),
        "name": name,
        "light_tag": payload["light_tag"],
        "care_tag": payload["care_tag"],
        "weight_class": payload["weight_class"],
        "unit_price_cents": unit_price,
        "warranty_days": warranty_days,
        "available_count": 0,
    }
    DB.plants[entity["id"]] = entity
    return created(entity)


@bp.get("/plants/<pid>")
def get_plant(pid):
    role, _ = auth_context()
    require_role(role, {"Anonymous", "Customer", "ShopStaff", "Manager", "Horticulturist"})
    entity = DB.plants.get(pid)
    if not entity:
        raise not_found("Plant")
    return ok(entity)


@bp.post("/plants/<pid>/stock-units")
def intake_stock_unit(pid):
    role, _ = auth_context()
    require_role(role, {"ShopStaff", "Manager"})
    if pid not in DB.plants:
        raise not_found("Plant")
    payload = require_json()
    require_fields(payload, ["acquisition_date"])
    acq = payload["acquisition_date"]
    dt = parse_iso(acq)
    if dt is None:
        raise invalid_request("acquisition_date must be ISO 8601 UTC")
    entity = {
        **stamp_common(full=True),
        "plant_id": pid,
        "acquisition_date": acq,
        "health_status": "HEALTHY",
        "sale_status": "FOR_SALE",
        "shrink_reason": "NONE",
    }
    DB.stock_units[entity["id"]] = entity
    recompute_available_count(pid)
    return created(entity)


@bp.get("/plants/<pid>/stock-units")
def list_plant_stock(pid):
    role, _ = auth_context()
    require_role(role, {"ShopStaff", "Manager", "Horticulturist"})
    if pid not in DB.plants:
        raise not_found("Plant")
    limit, offset = parse_pagination(request.args)
    hs = request.args.get("health_status")
    if hs is not None and hs not in HEALTH_STATUSES:
        raise invalid_request("invalid health_status filter")
    ss = request.args.get("sale_status")
    if ss is not None and ss not in SALE_STATUSES:
        raise invalid_request("invalid sale_status filter")
    rows = [s for s in DB.stock_units.values() if s["plant_id"] == pid]
    if hs:
        rows = [s for s in rows if s["health_status"] == hs]
    if ss:
        rows = [s for s in rows if s["sale_status"] == ss]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit=limit, offset=offset, total_count=total)


@bp.get("/stock-units/<sid>")
def get_stock_unit(sid):
    role, _ = auth_context()
    require_role(role, {"ShopStaff", "Manager", "Horticulturist"})
    entity = DB.stock_units.get(sid)
    if not entity:
        raise not_found("StockUnit")
    return ok(entity)


@bp.post("/stock-units/<sid>/adjust")
def adjust_stock_unit(sid):
    role, _ = auth_context()
    require_role(role, {"Manager"})
    entity = DB.stock_units.get(sid)
    if not entity:
        raise not_found("StockUnit")
    payload = require_json()
    require_fields(payload, ["expected_stock_unit_version"])
    exp = payload["expected_stock_unit_version"]
    if not isinstance(exp, int) or isinstance(exp, bool):
        raise invalid_request("expected_stock_unit_version must be integer")

    new_health = payload.get("health_status")
    new_sale = payload.get("sale_status")
    new_shrink = payload.get("shrink_reason")
    if new_health is not None:
        require_enum(new_health, HEALTH_STATUSES, "health_status")
    if new_sale is not None:
        require_enum(new_sale, SALE_STATUSES, "sale_status")
    if new_shrink is not None:
        require_enum(new_shrink, SHRINK_REASONS, "shrink_reason")

    # State precondition (priority 7) before OCC (priority 8). SHRINK->FOR_SALE
    # is priority-10 business_safety (ERR_STOCK_UNIT_UNHEALTHY) — evaluated
    # after OCC per §2.8.
    # Nothing state-machine here beyond forbidden shrink flip; enforce after OCC.

    if exp != entity["version"]:
        raise stale_version("stock unit version mismatch")

    # business_safety: SHRINK -> FOR_SALE forbidden.
    if new_sale is not None and entity["sale_status"] == "SHRINK" and new_sale == "FOR_SALE":
        raise ApiError(ERR_STOCK_UNIT_UNHEALTHY, 422, "cannot revive shrink")

    prev_sale = entity["sale_status"]
    if new_health is not None:
        entity["health_status"] = new_health
    if new_sale is not None:
        entity["sale_status"] = new_sale
    if new_shrink is not None:
        entity["shrink_reason"] = new_shrink
    bump(entity)
    recompute_available_count(entity["plant_id"])
    return ok(entity)


@bp.post("/stock-units/<sid>/care-log")
def append_care_log(sid):
    role, _ = auth_context()
    require_role(role, {"Horticulturist", "Manager"})
    entity = DB.stock_units.get(sid)
    if not entity:
        raise not_found("StockUnit")
    payload = require_json()
    require_fields(payload, ["entry_type"])
    require_enum(payload["entry_type"], ENTRY_TYPES, "entry_type")
    note = payload.get("note", "")
    if note is None:
        note = ""
    if not isinstance(note, str):
        raise invalid_request("note must be string")
    row = {
        **stamp_common(full=False),
        "stock_unit_id": sid,
        "entry_type": payload["entry_type"],
        "actor_role": role,
        "note": note,
        "entered_at": iso_now(),
    }
    DB.care_log_entries[row["id"]] = row
    return created(row)


@bp.get("/stock-units/<sid>/care-log")
def list_care_log(sid):
    role, _ = auth_context()
    require_role(role, {"Horticulturist", "Manager"})
    if sid not in DB.stock_units:
        raise not_found("StockUnit")
    limit, offset = parse_pagination(request.args)
    rows = [r for r in DB.care_log_entries.values() if r["stock_unit_id"] == sid]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit=limit, offset=offset, total_count=total)
