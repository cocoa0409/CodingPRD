"""CareUnit endpoints (PRD 3.1): unit_code unique per program."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_DUPLICATE_UNIT_CODE
from middleware import require_roles
from response import success_object, success_list
from serializers import unit_view
from util import (
    get_json_body, reject_unknown_fields, require_string, get_or_404,
    parse_pagination, paginate, sort_created, query_arg,
)

bp = Blueprint("units", __name__)


@bp.route("/api/units", methods=["POST"])
@require_roles("ProgramAdmin")
def create_unit(_user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, {"program_id", "name", "unit_code"})
    program_id = require_string(body, "program_id")
    name = require_string(body, "name")
    unit_code = require_string(body, "unit_code")

    get_or_404(db.programs, program_id, "SurveyProgram")

    for u in db.units.values():
        if u["program_id"] == program_id and u["unit_code"] == unit_code:
            raise_err(ERR_DUPLICATE_UNIT_CODE,
                      f"unit_code {unit_code} already exists in this program")

    unit = db.stamp_new({
        "program_id": program_id,
        "name": name,
        "unit_code": unit_code,
    })
    db.units[unit["id"]] = unit
    return success_object(unit_view(unit), 201)


@bp.route("/api/units", methods=["GET"])
@require_roles("Any")
def list_units(_user_id: str, _role: str):
    items = list(db.units.values())
    program_id = query_arg("program_id")
    if program_id is not None:
        items = [u for u in items if u["program_id"] == program_id]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([unit_view(u) for u in page], limit, offset, total)


@bp.route("/api/units/<unitId>", methods=["GET"])
@require_roles("Any")
def get_unit(unitId: str, _user_id: str, _role: str):
    unit = get_or_404(db.units, unitId, "CareUnit")
    return success_object(unit_view(unit))
