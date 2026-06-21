"""InventoryLot endpoints: intake, fetch, list, dispose (OCC), order-lines."""
from flask import Blueprint, request

from db import db
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_COLD_CHAIN_MISMATCH,
    ERR_COLD_STORAGE_CAPACITY_EXCEEDED,
    ERR_INVALID_STATE,
    ERR_STALE_LOT_VERSION,
)
from middleware import get_identity, require_role
from response import object_response, array_response
from services import models
from services.calc import round2
from services.validate import (
    get_json_body,
    parse_pagination,
    paginate,
    require_enum,
    require_number,
    require_int,
    optional_int,
)
from routes.lookups import get_unit, get_lot

bp = Blueprint("inventory", __name__)

READ_ROLES = {"FoodBankOperator", "AllocationManager", "ComplianceAuditor"}


@bp.post("/inventory-lots")
def intake_lot():
    user_id, role = get_identity()
    require_role(role, {"FoodBankOperator"})
    body = get_json_body()

    # priority 4: existence of FK before well-formedness of others? The PRD orders
    # existence (FK) before request well-formedness. The cold_storage_unit_id FK
    # must be a present string for lookup; absence/empty -> ERR_INVALID_REQUEST.
    if "cold_storage_unit_id" not in body or body["cold_storage_unit_id"] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: cold_storage_unit_id.")
    if not isinstance(body["cold_storage_unit_id"], str):
        raise err(ERR_INVALID_REQUEST, "cold_storage_unit_id must be a string.")
    unit = get_unit(body["cold_storage_unit_id"])  # ERR_NOT_FOUND if missing

    food_category = require_enum(body, "food_category", models.FOOD_CATEGORIES)
    source_type = require_enum(body, "source_type", models.SOURCE_TYPES)
    intake_lbs = require_number(body, "intake_lbs", positive=True)
    if "expiration_date" not in body or body["expiration_date"] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: expiration_date.")
    if not isinstance(body["expiration_date"], str):
        raise err(ERR_INVALID_REQUEST, "expiration_date must be a string.")
    try:
        models.parse_iso(body["expiration_date"])
    except Exception:
        raise err(ERR_INVALID_REQUEST, "expiration_date must be ISO 8601.")
    unit_cost_cents = optional_int(body, "unit_cost_cents", non_negative=True, default=0)

    required_zone = models.CATEGORY_TEMP_ZONE[food_category]

    # priority 7: cold-chain match
    if required_zone != unit["temp_zone"]:
        raise err(ERR_COLD_CHAIN_MISMATCH, "Lot temp zone does not match unit.")

    # priority 11: cold-storage capacity. Recompute occupancy then test would-exceed.
    models.recompute_unit_occupancy(unit)
    prospective = round2(unit["stored_lbs"] + intake_lbs)
    if prospective > unit["capacity_lbs"]:
        raise err(
            ERR_COLD_STORAGE_CAPACITY_EXCEEDED,
            "Lot intake would exceed cold storage unit capacity.",
        )

    lot = models._common_create()
    lot.update(
        {
            "cold_storage_unit_id": unit["id"],
            "food_category": food_category,
            "required_temp_zone": required_zone,
            "source_type": source_type,
            "intake_lbs": round2(intake_lbs),
            "remaining_lbs": round2(intake_lbs),
            "expiration_date": body["expiration_date"],
            "unit_cost_cents": unit_cost_cents,
            "disposition": "AVAILABLE",
        }
    )
    db.inventory_lots[lot["id"]] = lot
    models.recompute_unit_occupancy(unit)
    return object_response(models.serialize_lot(lot), status=201)


@bp.get("/inventory-lots/<lot_id>")
def fetch_lot(lot_id):
    user_id, role = get_identity()
    require_role(role, READ_ROLES)
    lot = get_lot(lot_id)
    return object_response(models.serialize_lot(lot))


@bp.get("/inventory-lots")
def list_lots():
    user_id, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    lots = list(db.inventory_lots.values())
    for key in ("cold_storage_unit_id", "food_category", "disposition", "source_type"):
        val = request.args.get(key)
        if val is not None:
            lots = [l for l in lots if l[key] == val]
    lots.sort(key=lambda l: l["_seq"])
    page, total = paginate(lots, limit, offset)
    return array_response([models.serialize_lot(l) for l in page], limit, offset, total)


@bp.post("/inventory-lots/<lot_id>/dispose")
def dispose_lot(lot_id):
    user_id, role = get_identity()
    require_role(role, {"FoodBankOperator"})
    lot = get_lot(lot_id)
    body = get_json_body()
    expected = require_int(body, "expected_lot_version")

    # priority 6: state legality (AVAILABLE or EXPIRED only).
    if lot["disposition"] not in ("AVAILABLE", "EXPIRED"):
        raise err(ERR_INVALID_STATE, "Lot cannot be disposed from its current state.")

    # priority 14: OCC on lot version.
    if expected != lot["version"]:
        raise err(ERR_STALE_LOT_VERSION, "Stale inventory lot version.")

    lot["disposition"] = "DISPOSED"
    lot["remaining_lbs"] = 0
    models.touch(lot)
    unit = db.cold_storage_units.get(lot["cold_storage_unit_id"])
    if unit is not None:
        models.recompute_unit_occupancy(unit)
    return object_response(models.serialize_lot(lot))


@bp.get("/inventory-lots/<lot_id>/order-lines")
def lot_order_lines(lot_id):
    user_id, role = get_identity()
    require_role(role, READ_ROLES)
    lot = get_lot(lot_id)
    limit, offset = parse_pagination()
    line_status = request.args.get("line_status")
    lines = [l for l in db.order_lines.values() if l["reserved_lot_id"] == lot["id"]]
    if line_status is not None:
        lines = [l for l in lines if l["line_status"] == line_status]
    lines.sort(key=lambda l: l["_seq"])
    page, total = paginate(lines, limit, offset)
    return array_response([models.serialize_line(l) for l in page], limit, offset, total)
