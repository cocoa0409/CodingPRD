"""Logical clock endpoints (PRD 2.5)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_REQUEST, ERR_TEMPORAL_VIOLATION
from middleware import require_roles
from response import success_object
from services.clockwork import advance_clock
from util import get_body, parse_datetime

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("SystemOperator")
def set_clock(_user_id: str, _role: str):
    body = get_body()
    to_iso = body.get("to_iso8601")
    if to_iso is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: to_iso8601")
    new_dt = parse_datetime(to_iso)
    if new_dt is None:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO-8601 datetime")
    current_dt = db.get_current_utc_dt()
    if new_dt < current_dt:
        raise_err(ERR_TEMPORAL_VIOLATION, "Logical clock must be monotonically non-decreasing")
    # Preserve the caller's string for perfect round-trip fidelity.
    db.set_current_utc(to_iso.strip())
    advance_clock(new_dt)
    return success_object({"current_utc": db.get_current_utc()})


@bp.route("/_clock/current_utc", methods=["GET"])
@require_roles("Any")
def get_clock(_user_id: str, _role: str):
    return success_object({"current_utc": db.get_current_utc()})
