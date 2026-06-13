"""ColdStorageUnit endpoints."""
from flask import Blueprint

from db import db
from errors import err, ERR_INVALID_REQUEST
from middleware import get_identity, require_role
from response import object_response, array_response
from services import models
from services.calc import round2
from services.validate import (
    get_json_body,
    parse_pagination,
    paginate,
    require_string,
    require_enum,
    require_number,
)
from routes.lookups import get_unit

bp = Blueprint("cold_storage", __name__)

READ_ROLES = {"FoodBankOperator", "AllocationManager", "ComplianceAuditor"}


@bp.post("/cold-storage-units")
def create_unit():
    user_id, role = get_identity()
    require_role(role, {"FoodBankOperator"})
    body = get_json_body()
    name = require_string(body, "name")
    temp_zone = require_enum(body, "temp_zone", models.TEMP_ZONES)
    capacity = require_number(body, "capacity_lbs", positive=True)

    unit = models._common_create()
    unit.update(
        {
            "name": name,
            "temp_zone": temp_zone,
            "capacity_lbs": round2(capacity),
            "stored_lbs": 0,
            "status": "AVAILABLE",
        }
    )
    db.cold_storage_units[unit["id"]] = unit
    return object_response(models.serialize_unit(unit), status=201)


@bp.get("/cold-storage-units/<unit_id>")
def fetch_unit(unit_id):
    user_id, role = get_identity()
    require_role(role, READ_ROLES)
    unit = get_unit(unit_id)
    models.recompute_unit_occupancy(unit)
    return object_response(models.serialize_unit(unit))


@bp.get("/cold-storage-units")
def list_units():
    from flask import request

    user_id, role = get_identity()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    temp_zone = request.args.get("temp_zone")
    status = request.args.get("status")

    units = list(db.cold_storage_units.values())
    for u in units:
        models.recompute_unit_occupancy(u)
    if temp_zone is not None:
        units = [u for u in units if u["temp_zone"] == temp_zone]
    if status is not None:
        units = [u for u in units if u["status"] == status]
    units.sort(key=lambda u: u["_seq"])
    page, total = paginate(units, limit, offset)
    return array_response([models.serialize_unit(u) for u in page], limit, offset, total)


@bp.get("/cold-storage-units/<unit_id>/inventory-lots")
def list_unit_lots(unit_id):
    from flask import request

    user_id, role = get_identity()
    require_role(role, READ_ROLES)
    unit = get_unit(unit_id)
    limit, offset = parse_pagination()
    disposition = request.args.get("disposition")

    lots = [l for l in db.inventory_lots.values() if l["cold_storage_unit_id"] == unit["id"]]
    if disposition is not None:
        lots = [l for l in lots if l["disposition"] == disposition]
    lots.sort(key=lambda l: l["_seq"])
    page, total = paginate(lots, limit, offset)
    return array_response([models.serialize_lot(l) for l in page], limit, offset, total)
