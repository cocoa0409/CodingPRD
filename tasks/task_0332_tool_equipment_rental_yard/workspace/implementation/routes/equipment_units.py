"""EquipmentUnit endpoints (PRD §3.2)."""
from flask import Blueprint, request

import errors
from db import DB, LOCK
from middleware import require_auth
from services.common import new_record, require_body, req_str, req_int, get_or_404
from .helpers import get_json_body, list_response, single_response

bp = Blueprint("equipment_units", __name__)


@bp.post("/rental-yard/equipment-units")
def create_equipment_unit():
    require_auth({"YardManager"})
    body = require_body(get_json_body())

    # Existence (PRD §2.5): catalog_item_id checked before business rules.
    catalog_item_id = body.get("catalog_item_id")
    if not isinstance(catalog_item_id, str):
        raise errors.invalid_request("Field 'catalog_item_id' must be a string.")
    if catalog_item_id not in DB.catalog_items:
        raise errors.not_found()

    asset_tag = req_str(body, "asset_tag", 1, 40)
    service_due = req_int(body, "service_due_at_days", 1)

    with LOCK:
        # asset_tag unique across all units -> ERR_DUPLICATE_KEY (PRD §3.2).
        for u in DB.equipment_units.values():
            if u["asset_tag"] == asset_tag:
                raise errors.duplicate_key("An equipment unit with this asset_tag already exists.")

        rec = new_record({
            "catalog_item_id": catalog_item_id,
            "asset_tag": asset_tag,
            "availability_state": "AVAILABLE",
            "fuel_level_liters": 0,
            "lifetime_rental_days": 0,
            "service_due_at_days": service_due,
        })
        DB.equipment_units[rec["id"]] = rec
    return single_response(rec, 201)


@bp.get("/rental-yard/equipment-units/<rid>")
def get_equipment_unit(rid):
    rec = get_or_404(DB.equipment_units, rid)
    return single_response(rec)


@bp.get("/rental-yard/equipment-units")
def list_equipment_units():
    catalog_item_id = request.args.get("catalog_item_id")
    availability_state = request.args.get("availability_state")
    units = DB.equipment_units.values()
    if catalog_item_id is not None:
        units = [u for u in units if u["catalog_item_id"] == catalog_item_id]
    if availability_state is not None:
        units = [u for u in units if u["availability_state"] == availability_state]
    return list_response(units)
