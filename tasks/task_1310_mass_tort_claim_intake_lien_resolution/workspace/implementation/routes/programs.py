"""Program CRUD + clock endpoints."""

from flask import Blueprint

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from middleware import require_role
from response import success_envelope
from routes.helpers import (
    get_json_body,
    get_pagination,
    new_common_fields,
    paginate,
    require_fields,
    resolve_program,
    sort_by_created_at,
)

bp = Blueprint("programs", __name__)

ALL_ROLES = (
    "ProgramAdministrator",
    "IntakeSpecialist",
    "RecordsAnalyst",
    "LienAnalyst",
    "DisbursementApprover",
    "ClaimantRole",
)


@bp.route("/settlement-programs", methods=["POST"])
def create_program():
    user_id, role = require_role("ProgramAdministrator")
    body = get_json_body()
    require_fields(body, ["program_code", "tort_name", "qsf_principal_cents"])

    prog = {
        "program_code": body["program_code"],
        "tort_name": body["tort_name"],
        "current_utc": "2026-08-01T00:00:00Z",
        "qsf_principal_cents": body["qsf_principal_cents"],
        "qsf_remaining_cents": body["qsf_principal_cents"],
        "matrix_published": False,
    }
    prog.update(new_common_fields())
    db.programs[prog["id"]] = prog
    return success_envelope(prog, 201, "object")


@bp.route("/settlement-programs", methods=["GET"])
def list_programs():
    user_id, role = require_role(*ALL_ROLES)
    limit, offset = get_pagination()
    items = sort_by_created_at(list(db.programs.values()))
    page, meta = paginate(items, limit, offset)
    return success_envelope(page, 200, "array", meta)


@bp.route("/settlement-programs/<pid>", methods=["GET"])
def get_program(pid):
    user_id, role = require_role(*ALL_ROLES)
    prog = resolve_program(pid)
    return success_envelope(prog, 200, "object")


@bp.route("/settlement-programs/<pid>/_clock/set_current_utc", methods=["POST"])
def set_clock(pid):
    user_id, role = require_role("ProgramAdministrator")
    prog = resolve_program(pid)
    body = get_json_body()
    require_fields(body, ["to_iso8601"])

    to_iso = body["to_iso8601"]
    if not isinstance(to_iso, str):
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 must be a string", 400)
    if to_iso <= prog["current_utc"]:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "to_iso8601 must be strictly later than current value",
            400,
        )

    prog["current_utc"] = to_iso
    from routes.helpers import bump
    bump(prog)
    return success_envelope(prog, 200, "object")
