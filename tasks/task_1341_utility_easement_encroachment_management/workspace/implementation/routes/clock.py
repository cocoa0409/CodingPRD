"""Logical clock endpoint (PRD 2.10). Available to all five roles."""

from __future__ import annotations

from flask import Blueprint

import db
from constants import (
    ROLE_DEPARTMENT_DIRECTOR as DD,
    ROLE_LITIGATION_COUNSEL as LC,
    ROLE_RIGHT_OF_WAY_AGENT as RoWA,
    ROLE_TITLE_EXAMINER as TE,
    ROLE_VEGETATION_INSPECTOR as VI,
)
from middleware import require_roles
from response import success_object
from services import domain
from util import get_json_body, parse_iso8601, require_field

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles(RoWA, TE, VI, LC, DD)
def set_current_utc(_user_id: str, _role: str):
    body = get_json_body()
    to_iso8601 = require_field(body, "to_iso8601")
    new_dt = parse_iso8601(to_iso8601, "to_iso8601")
    db.set_current_utc(to_iso8601, new_dt)
    # Advancing the clock re-evaluates every deadline-based automatic
    # transition in the system.
    domain.sweep_deadlines()
    return success_object({"current_utc": db.get_current_utc()})
