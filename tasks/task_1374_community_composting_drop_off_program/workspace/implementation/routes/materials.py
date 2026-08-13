"""MaterialCategory endpoints."""

from flask import Blueprint, request

import db
import errors
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from routes.helpers import (
    body, require_fields, require_str, require_enum, parse_bool_param,
    get_program_or_404, get_material_or_404, paginate, sort_created,
)
from services.programs import touch
from services.serializers import material as serialize_material

bp = Blueprint("materials", __name__)

READ_ROLES = ALL_ROLES
SENSITIVITIES = ("LOW", "MEDIUM", "HIGH")


def _valid_mm_dd(s):
    if not isinstance(s, str) or len(s) != 5 or s[2] != "-":
        return False
    try:
        mm = int(s[:2])
        dd = int(s[3:])
    except ValueError:
        return False
    return 1 <= mm <= 12 and 1 <= dd <= 31


@bp.route("/programs/<program_id>/materials", methods=["POST"])
def create_material(program_id):
    require_roles("ProgramAdmin")
    program = get_program_or_404(program_id)
    data = body()
    require_fields(
        data, "code", "description", "accepted_start_month_day",
        "accepted_end_month_day", "contamination_sensitivity",
    )
    code = require_str(data, "code")
    description = require_str(data, "description")
    start_md = require_str(data, "accepted_start_month_day")
    end_md = require_str(data, "accepted_end_month_day")
    if not _valid_mm_dd(start_md) or not _valid_mm_dd(end_md):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "month-day fields must be MM-DD")
    sensitivity = require_enum(data, "contamination_sensitivity", SENSITIVITIES)
    active = data.get("active", True)
    if not isinstance(active, bool):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "active must be a boolean")

    now = db.iso_now()
    material = {
        "id": db.new_id(),
        "program_id": program["id"],
        "code": code,
        "description": description,
        "accepted_start_month_day": start_md,
        "accepted_end_month_day": end_md,
        "contamination_sensitivity": sensitivity,
        "active": active,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.materials[material["id"]] = material
    return success_object(serialize_material(material), status=201)


@bp.route("/programs/<program_id>/materials", methods=["GET"])
def list_materials(program_id):
    require_roles(*READ_ROLES)
    get_program_or_404(program_id)
    items = [m for m in db.materials.values() if m["program_id"] == program_id]
    active_filter = parse_bool_param("active")
    if active_filter is not None:
        items = [m for m in items if m["active"] == active_filter]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_material(m) for m in page], limit, offset, total)


@bp.route("/programs/<program_id>/materials/<material_id>", methods=["PATCH"])
def patch_material(program_id, material_id):
    require_roles("ProgramAdmin")
    get_program_or_404(program_id)
    material = get_material_or_404(material_id, program_id)
    data = body()
    if "active" in data:
        if not isinstance(data["active"], bool):
            errors.raise_err(errors.ERR_INVALID_REQUEST, "active must be a boolean")
        material["active"] = data["active"]
    if "description" in data:
        if not isinstance(data["description"], str):
            errors.raise_err(errors.ERR_INVALID_REQUEST, "description must be a string")
        material["description"] = data["description"]
    touch(material)
    return success_object(serialize_material(material))


# --- Flat aliases ---

@bp.route("/materials", methods=["GET"])
def list_materials_flat():
    require_roles(*READ_ROLES)
    items = list(db.materials.values())
    if request.args.get("program_id"):
        items = [m for m in items if m["program_id"] == request.args["program_id"]]
    active_filter = parse_bool_param("active")
    if active_filter is not None:
        items = [m for m in items if m["active"] == active_filter]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_material(m) for m in page], limit, offset, total)


@bp.route("/materials/<material_id>", methods=["GET"])
def get_material_flat(material_id):
    require_roles(*READ_ROLES)
    material = get_material_or_404(material_id)
    return success_object(serialize_material(material))
