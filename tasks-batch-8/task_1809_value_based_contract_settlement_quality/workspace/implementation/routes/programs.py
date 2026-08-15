"""Program endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_FOUND,
    ERR_PROGRAM_HAS_OPEN_CONTRACTS,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    reject_unknown_fields,
    require_enum,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("programs", __name__)

LINE_OF_BUSINESS = {"MEDICARE_ADVANTAGE", "MEDICAID_MANAGED_CARE", "COMMERCIAL_ACO"}


@bp.route("/vbc/programs", methods=["POST"])
@require_roles("PayerAdmin")
def create_program(_user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, {"program_name", "line_of_business"})
    program_name = require_string(body, "program_name")
    line_of_business = require_enum(body, "line_of_business", LINE_OF_BUSINESS)

    program = {
        "program_name": program_name,
        "line_of_business": line_of_business,
        "program_status": "DRAFT",
    }
    db.stamp_new(program)
    db.programs[program["id"]] = program
    return success_object(program, 201)


@bp.route("/vbc/programs", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_programs(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.programs.values()))
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/vbc/programs/<program_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_program(program_id: str, _user_id: str, _role: str):
    program = db.programs.get(program_id)
    if program is None:
        raise_err(ERR_NOT_FOUND, "Program id does not exist")
    return success_object(program)


@bp.route("/vbc/programs/<program_id>/activate", methods=["POST"])
@require_roles("PayerAdmin")
def activate_program(program_id: str, _user_id: str, _role: str):
    program = db.programs.get(program_id)
    if program is None:
        raise_err(ERR_NOT_FOUND, "Program id does not exist")
    if program["program_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a DRAFT program can be activated")
    program["program_status"] = "ACTIVE"
    db.touch(program)
    return success_object(program)


@bp.route("/vbc/programs/<program_id>/archive", methods=["POST"])
@require_roles("PayerAdmin")
def archive_program(program_id: str, _user_id: str, _role: str):
    program = db.programs.get(program_id)
    if program is None:
        raise_err(ERR_NOT_FOUND, "Program id does not exist")
    if program["program_status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an ACTIVE program can be archived")
    # State-family precondition: no DRAFT/ACTIVE contracts of this program.
    for contract in db.contracts.values():
        if contract["program_id"] == program_id and contract["contract_status"] in ("DRAFT", "ACTIVE"):
            raise_err(ERR_PROGRAM_HAS_OPEN_CONTRACTS, "Program has open contracts")
    program["program_status"] = "ARCHIVED"
    db.touch(program)
    return success_object(program)
