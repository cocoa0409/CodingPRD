"""Logical clock endpoints (PRD §2.4)."""
from __future__ import annotations

from flask import Blueprint

import db
from middleware import require
from response import ok_object
from services import serialize
from services.common import get_body, parse_dt, require_present

bp = Blueprint("clock", __name__)

ALL_ROLES = (
    "TerminalAdmin",
    "BerthPlanner",
    "YardPlanner",
    "GateOperator",
    "CustomsOfficer",
    "ReeferTechnician",
)


@bp.post("/_clock/set")
@require("TerminalAdmin")
def set_clock():
    body = get_body()
    to_iso = require_present(body, "to_iso8601")
    # validate it parses as a datetime, then store the supplied string
    parse_dt(to_iso)
    db.clock_set(to_iso)
    return ok_object(serialize.clock())


@bp.get("/_clock")
@require(*ALL_ROLES)
def get_clock():
    return ok_object(serialize.clock())
