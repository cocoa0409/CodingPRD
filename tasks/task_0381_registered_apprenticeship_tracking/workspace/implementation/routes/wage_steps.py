"""Wage step endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
from common import (
    get_json_body,
    parse_pagination,
    require_int,
    require_number,
    require_str,
    serialize,
    serialize_list,
    sort_and_paginate,
)
from errors import err
from lookups import get_program, get_wage_step
from middleware import require_roles
from response import success_array, success_object

bp = Blueprint("wage_steps", __name__)


@bp.route("/apprenticeship/wage-steps", methods=["POST"])
@require_roles("Sponsor")
def create_wage_step():
    body = get_json_body()
    program_id = require_str(body, "program_id")
    step_number = require_int(body, "step_number", minimum=1)
    ojt_hours_threshold = require_int(body, "ojt_hours_threshold", minimum=0)
    wage_pct = require_number(body, "wage_pct")

    program = get_program(program_id)
    if program["status"] != "DRAFT":
        raise err("ERR_PROGRAM_NOT_DRAFT", "Wage steps may only be added while the program is DRAFT.")

    # Uniqueness: step_number unique per program.
    if any(
        w["program_id"] == program_id and w["step_number"] == step_number
        for w in db.wage_steps.values()
    ):
        raise err("ERR_DUPLICATE_RESOURCE", "step_number already exists for this program.")

    rec = db.base_record(common_fields=True)
    rec.update(
        {
            "program_id": program_id,
            "step_number": step_number,
            "ojt_hours_threshold": ojt_hours_threshold,
            "wage_pct": wage_pct,
        }
    )
    db.wage_steps[rec["id"]] = rec
    return success_object(serialize(rec), status=201)


@bp.route("/apprenticeship/wage-steps", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator", "Apprentice")
def list_wage_steps():
    limit, offset = parse_pagination()
    items = list(db.wage_steps.values())
    program_id = request.args.get("program_id")
    if program_id is not None:
        items = [w for w in items if w["program_id"] == program_id]
    page, total = sort_and_paginate(items, limit, offset)
    return success_array(serialize_list(page), limit, offset, total)


@bp.route("/apprenticeship/wage-steps/<wid>", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator", "Apprentice")
def get_wage_step_route(wid):
    rec = get_wage_step(wid)
    return success_object(serialize(rec))
