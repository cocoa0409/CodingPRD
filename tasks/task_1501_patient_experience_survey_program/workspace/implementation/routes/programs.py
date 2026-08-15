"""SurveyProgram endpoints (PRD 3.1)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success_object
from serializers import program_view
from util import get_json_body, reject_unknown_fields, require_string, require_enum, get_or_404

bp = Blueprint("programs", __name__)

SAMPLING_PROTOCOLS = {"SIMPLE_RANDOM", "STRATIFIED_BY_UNIT", "CENSUS"}
ADMIN_MODES = {"MAIL_ONLY", "PHONE_ONLY", "MIXED_MODE"}


@bp.route("/api/survey-programs", methods=["POST"])
@require_roles("ProgramAdmin")
def create_program(_user_id: str, _role: str):
    body = get_json_body()
    reject_unknown_fields(body, {"name", "sampling_protocol", "admin_mode"})
    name = require_string(body, "name")
    sampling_protocol = require_enum(body, "sampling_protocol", SAMPLING_PROTOCOLS)
    admin_mode = require_enum(body, "admin_mode", ADMIN_MODES)

    program = db.stamp_new({
        "name": name,
        "sampling_protocol": sampling_protocol,
        "admin_mode": admin_mode,
        "active_vendor_id": None,
    })
    db.programs[program["id"]] = program
    return success_object(program_view(program), 201)


@bp.route("/api/survey-programs/<programId>", methods=["GET"])
@require_roles("Any")
def get_program(programId: str, _user_id: str, _role: str):
    program = get_or_404(db.programs, programId, "SurveyProgram")
    return success_object(program_view(program))
