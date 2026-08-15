"""Logical clock control (PRD §2.4). Stands outside the /tnr prefix."""

from flask import Blueprint

from db import db
from middleware import json_body, require_roles
from response import success_object
from util import parse_datetime, req_field

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("ProgramCoordinator")
def set_current_utc(user_id, role):
    body = json_body()
    db.clock = parse_datetime(req_field(body, "to_iso8601"), "to_iso8601")
    return success_object({}, status=200)
