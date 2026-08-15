"""ComplianceRule endpoints."""

from flask import Blueprint, request

import db
import errors
import response
from middleware import require_roles, get_auth
from services.common import (
    new_common_fields, require_enum, require_string, paginate,
    sort_by_created, serialize, recompute_program_designs,
)

bp = Blueprint("compliance_rules", __name__)

DIMENSIONS = {"MAX_WIDTH_IN", "MAX_HEIGHT_IN", "MAX_DEPTH_IN", "ALLOWED_MATERIAL", "MAX_WEIGHT_LB"}


@bp.route("/pop/programs/<program_id>/compliance-rules", methods=["POST"])
@require_roles("ComplianceOfficer")
def create_rule(program_id):
    program = db.programs.get(program_id)
    if not program:
        raise errors.err_not_found("Program not found")
    body = request.get_json(silent=True) or {}
    dimension = require_enum(body, "dimension", DIMENSIONS)
    limit_value = require_string(body, "limit_value") if not isinstance(body.get("limit_value"), (int, float)) else body["limit_value"]
    # limit_value is string-typed in scaffold but accept numeric for MAX_* and normalize to string
    if not isinstance(limit_value, str):
        limit_value = str(limit_value)
    active = body.get("active", True)
    if not isinstance(active, bool):
        raise errors.err_invalid_request("Field active must be a boolean")

    rule = new_common_fields()
    rule.update({
        "program_id": program_id,
        "dimension": dimension,
        "limit_value": limit_value,
        "active": active,
    })
    db.compliance_rules[rule["id"]] = rule
    # Side effect: recompute compliance_result on all non-terminal designs in program
    recompute_program_designs(program_id)
    return response.success_object(serialize(rule), 201)


@bp.route("/pop/programs/<program_id>/compliance-rules", methods=["GET"])
def list_rules(program_id):
    _, role = get_auth()
    if role not in ("PlatformAdmin", "ProgramManager", "ComplianceOfficer", "Designer"):
        raise errors.err_unauthorized()
    program = db.programs.get(program_id)
    if not program:
        raise errors.err_not_found("Program not found")
    items = sort_by_created([r for r in db.compliance_rules.values() if r["program_id"] == program_id])
    page, limit, offset, total = paginate(items, request.args)
    return response.success_list([serialize(r) for r in page], limit, offset, total)
