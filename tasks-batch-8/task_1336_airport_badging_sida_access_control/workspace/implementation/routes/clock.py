"""Logical clock endpoint (PRD §2.5) — test-driving capability."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success_object
from services import logic
from util import get_json_body, require_field

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("BadgingOfficer", "SecurityManager", "Auditor")
def set_current_utc(user_id: str, role: str):
    body = get_json_body()
    raw = require_field(body, "to_iso8601")
    new_dt = db.parse_datetime(raw)
    if new_dt is None:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 datetime")

    db.set_clock(new_dt, raw.strip() if isinstance(raw, str) else raw)
    # Setting the clock atomically sweeps every time-driven transition.
    logic.sweep_clock(new_dt)

    return success_object({"current_utc": db.CLOCK["raw"]})
