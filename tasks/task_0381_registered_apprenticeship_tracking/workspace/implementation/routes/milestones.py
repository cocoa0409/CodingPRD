"""Milestone endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
from common import (
    get_json_body,
    optional_bool,
    parse_pagination,
    require_int,
    require_str,
    serialize,
    serialize_list,
    sort_and_paginate,
)
from errors import err
from lookups import get_milestone, get_program
from middleware import require_roles
from response import success_array, success_object

bp = Blueprint("milestones", __name__)


@bp.route("/apprenticeship/milestones", methods=["POST"])
@require_roles("Sponsor")
def create_milestone():
    body = get_json_body()
    program_id = require_str(body, "program_id")
    sequence = require_int(body, "sequence", minimum=1)
    title = require_str(body, "title")
    required_for_completion = optional_bool(body, "required_for_completion", default=True)

    program = get_program(program_id)
    if program["status"] != "DRAFT":
        raise err("ERR_PROGRAM_NOT_DRAFT", "Milestones may only be added while the program is DRAFT.")

    if any(
        m["program_id"] == program_id and m["sequence"] == sequence
        for m in db.milestones.values()
    ):
        raise err("ERR_DUPLICATE_RESOURCE", "sequence already exists for this program.")

    rec = db.base_record(common_fields=True)
    rec.update(
        {
            "program_id": program_id,
            "sequence": sequence,
            "title": title,
            "required_for_completion": required_for_completion,
        }
    )
    db.milestones[rec["id"]] = rec
    return success_object(serialize(rec), status=201)


@bp.route("/apprenticeship/milestones", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator", "Apprentice")
def list_milestones():
    limit, offset = parse_pagination()
    items = list(db.milestones.values())
    program_id = request.args.get("program_id")
    if program_id is not None:
        items = [m for m in items if m["program_id"] == program_id]
    page, total = sort_and_paginate(items, limit, offset)
    return success_array(serialize_list(page), limit, offset, total)


@bp.route("/apprenticeship/milestones/<mid>", methods=["GET"])
@require_roles("RegistrationAgency", "Sponsor", "TrainingCoordinator", "Apprentice")
def get_milestone_route(mid):
    rec = get_milestone(mid)
    return success_object(serialize(rec))
