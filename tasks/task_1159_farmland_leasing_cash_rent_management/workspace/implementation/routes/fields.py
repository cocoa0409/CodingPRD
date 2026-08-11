from flask import Blueprint, request
from middleware import get_caller, require_role, get_json_body
from services.common import (require_string, require_int, require_number,
                             optional_enum, parse_pagination)
from response import success_object, success_list
from errors import ApiError
from db import db, new_common
from services.serialize import serialize

bp = Blueprint("fields", __name__)
READ_ROLES = {"FarmManager", "Landlord", "Tenant"}
DRAINAGE = {"POOR", "ADEQUATE", "TILED"}


@bp.route("/fields", methods=["POST"])
def create_field():
    _, role = get_caller()
    require_role(role, {"FarmManager"})
    body = get_json_body()
    landlord_id = require_string(body, "landlord_id")
    name = require_string(body, "name")
    acres = require_int(body, "acres", minimum=1)
    soil = require_number(body, "soil_csr2", minimum=0, maximum=100)
    drainage = optional_enum(body, "drainage_status", DRAINAGE, default="ADEQUATE")

    if landlord_id not in db.landlords:
        raise ApiError("ERR_NOT_FOUND", 404, f"Landlord {landlord_id} not found")

    rec = new_common()
    rec.update({
        "landlord_id": landlord_id,
        "name": name,
        "acres": acres,
        "soil_csr2": soil,
        "drainage_status": drainage,
        "status": "AVAILABLE",
    })
    db.fields[rec["id"]] = rec
    return success_object(serialize("field", rec), status=201)


@bp.route("/fields/<fieldId>", methods=["GET"])
def get_field(fieldId):
    _, role = get_caller()
    require_role(role, READ_ROLES)
    rec = db.fields.get(fieldId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Field {fieldId} not found")
    return success_object(serialize("field", rec))


@bp.route("/fields", methods=["GET"])
def list_fields():
    _, role = get_caller()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = sorted(db.fields.values(), key=lambda r: r["created_at"])
    landlord_q = request.args.get("landlord_id")
    if landlord_q is not None:
        items = [r for r in items if r["landlord_id"] == landlord_q]
    status_q = request.args.get("status")
    if status_q is not None:
        items = [r for r in items if r["status"] == status_q]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize("field", r) for r in page], limit, offset, total)
