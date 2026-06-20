"""InputProduct + InputLot endpoints (PRD §3.3)."""
from flask import Blueprint, request

import db
import lookups
import serializers
from errors import err
from helpers import (
    as_number,
    get_json_body,
    optional_bool,
    paginate,
    parse_pagination,
    require_enum,
    require_number,
    require_str,
)
from middleware import require_roles
from response import array_response, object_response

bp = Blueprint("input_products", __name__)

CATEGORIES = {"SEED", "FERTILIZER", "CHEMICAL"}
UNITS = {"LB", "GAL", "SEED_UNIT", "TON"}
READ_ROLES = ("FarmManager", "Agronomist", "Applicator")


@bp.post("/input-products")
@require_roles("FarmManager")
def create_input_product():
    body = get_json_body()
    name = require_str(body, "name")
    category = require_enum(body, "category", CATEGORIES)
    unit = require_enum(body, "unit", UNITS)
    unit_cost = require_number(body, "unit_cost")
    if unit_cost < 0:
        raise err("ERR_INVALID_REQUEST", "unit_cost must be >= 0.")
    restricted_use = optional_bool(body, "restricted_use", False)

    # REI/PHI required when restricted_use is true; else default 0 (PRD §3.3).
    def _opt_int(name, default):
        if name not in body or body.get(name) is None:
            return default
        v = body.get(name)
        if isinstance(v, bool) or not isinstance(v, int):
            raise err("ERR_INVALID_REQUEST", f"{name} must be an integer.")
        return v

    if restricted_use:
        if "reentry_interval_hours" not in body or body.get("reentry_interval_hours") is None:
            raise err("ERR_INVALID_REQUEST", "reentry_interval_hours is required for restricted_use.")
        if "preharvest_interval_days" not in body or body.get("preharvest_interval_days") is None:
            raise err("ERR_INVALID_REQUEST", "preharvest_interval_days is required for restricted_use.")
    reentry_interval_hours = _opt_int("reentry_interval_hours", 0)
    preharvest_interval_days = _opt_int("preharvest_interval_days", 0)

    max_rate = None
    if "max_seasonal_rate_per_acre" in body and body.get("max_seasonal_rate_per_acre") is not None:
        max_rate = as_number(body.get("max_seasonal_rate_per_acre"))
        if max_rate is None:
            raise err("ERR_INVALID_REQUEST", "max_seasonal_rate_per_acre must be a number.")

    rec = db.new_entity(
        {
            "name": name,
            "category": category,
            "unit": unit,
            "unit_cost": unit_cost,
            "restricted_use": restricted_use,
            "reentry_interval_hours": reentry_interval_hours,
            "preharvest_interval_days": preharvest_interval_days,
            "max_seasonal_rate_per_acre": max_rate,
        }
    )
    db.input_products[rec["id"]] = rec
    return object_response(serializers.input_product(rec), 201)


@bp.get("/input-products/<pid>")
@require_roles(*READ_ROLES)
def get_input_product(pid):
    rec = lookups.input_product(pid)
    return object_response(serializers.input_product(rec))


@bp.get("/input-products/<pid>/lots")
@require_roles(*READ_ROLES)
def list_product_lots(pid):
    lookups.input_product(pid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    records = [l for l in db.input_lots.values() if l["input_product_id"] == pid]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return array_response(
        [serializers.input_lot(r) for r in page], limit, offset, total
    )


@bp.post("/input-lots")
@require_roles("FarmManager")
def create_input_lot():
    body = get_json_body()
    input_product_id = require_str(body, "input_product_id")
    lot_code = require_str(body, "lot_code")
    quantity_received = require_number(body, "quantity_received")

    lookups.input_product(input_product_id)

    if quantity_received <= 0:
        raise err("ERR_INVALID_REQUEST", "quantity_received must be > 0.")

    rec = db.new_entity(
        {
            "input_product_id": input_product_id,
            "lot_code": lot_code,
            "quantity_received": quantity_received,
            "quantity_remaining": quantity_received,
            "status": "OPEN",
        }
    )
    db.input_lots[rec["id"]] = rec
    return object_response(serializers.input_lot(rec), 201)


@bp.get("/input-lots/<lid>")
@require_roles(*READ_ROLES)
def get_input_lot(lid):
    rec = lookups.input_lot(lid)
    return object_response(serializers.input_lot(rec))
