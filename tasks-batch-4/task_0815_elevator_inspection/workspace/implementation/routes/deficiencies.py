from flask import Blueprint, request

import errors
from auth import require
from common import lookup, paginate, parse_pagination
from envelope import array_response, object_response
from services.logic import serialize_deficiency
from store import db, touch

bp = Blueprint("deficiencies", __name__)


@bp.route("/deficiencies/<deficiency_id>", methods=["GET"])
@require("Registrar", "SafetyAdministrator", "LicensedInspector", "BuildingOwner")
def get_deficiency(deficiency_id):
    d = lookup(db.deficiencies, deficiency_id, "ERR_DEFICIENCY_NOT_FOUND")
    return object_response(serialize_deficiency(d), 200)


@bp.route("/deficiencies", methods=["GET"])
@require("Registrar", "SafetyAdministrator", "LicensedInspector", "BuildingOwner")
def list_deficiencies():
    limit, offset = parse_pagination()
    inspection_id = request.args.get("inspection_id")
    device_id = request.args.get("device_id")
    status = request.args.get("status")
    severity = request.args.get("severity")
    items = list(db.deficiencies.values())
    if inspection_id is not None:
        items = [d for d in items if d["inspection_id"] == inspection_id]
    if device_id is not None:
        items = [d for d in items if d["device_id"] == device_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    if severity is not None:
        items = [d for d in items if d["severity"] == severity]
    page, total = paginate(items, limit, offset)
    return array_response([serialize_deficiency(d) for d in page], limit, offset, total)


@bp.route("/deficiencies/<deficiency_id>/resolve", methods=["POST"])
@require("LicensedInspector")
def resolve_deficiency(deficiency_id):
    d = lookup(db.deficiencies, deficiency_id, "ERR_DEFICIENCY_NOT_FOUND")
    if d["status"] not in ("OPEN", "CITED"):
        raise errors.ApiError("ERR_DEFICIENCY_NOT_RESOLVABLE", 409,
                              "Deficiency is not resolvable.")
    d["status"] = "RESOLVED"
    touch(d)
    return object_response(serialize_deficiency(d), 200)
