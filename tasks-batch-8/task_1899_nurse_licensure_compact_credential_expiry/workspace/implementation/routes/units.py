from flask import Blueprint

from errors import ERR_DUPLICATE_RESOURCE, ERR_NOT_FOUND, ApiError
from middleware import auth_context, get_body, pagination_params, require_role, validate_body
from response import success_list, success_object
from services.core import all_entities, create_entity, get_or_404, serialize

bp = Blueprint("units", __name__)

CERT_TYPES = ["BLS", "ACLS", "PALS", "CCRN", "CNOR", "OCN"]

CREATE_SCHEMA = {
    "name": ("string", True, None),
    "required_cert_types": ("array_enum", False, CERT_TYPES),
}


@bp.route("/credentialing/units", methods=["POST"])
def create_unit():
    user_id, role = auth_context()
    require_role(role, {"NurseManager"})
    body = validate_body(get_body(), CREATE_SCHEMA)
    if any(u["name"] == body["name"] for u in all_entities("units")):
        raise ApiError(ERR_DUPLICATE_RESOURCE, "A unit with this name already exists", 409)
    unit = create_entity("units", {
        "name": body["name"],
        "required_cert_types": body.get("required_cert_types", []),
        "scheduled_hours_total": 0,
        "active_assignment_count": 0,
    })
    return success_object(serialize("units", unit), 201)


@bp.route("/credentialing/units", methods=["GET"])
def list_units():
    auth_context()
    limit, offset = pagination_params()
    rows = all_entities("units")
    total = len(rows)
    return success_list([serialize("units", u) for u in rows[offset:offset + limit]], limit, offset, total)


@bp.route("/credentialing/units/<unitId>", methods=["GET"])
def get_unit(unitId):
    auth_context()
    unit = get_or_404("units", unitId, ERR_NOT_FOUND, "Unit not found")
    return success_object(serialize("units", unit))
