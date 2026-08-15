"""Logical clock endpoint (PRD 2.6).

Exempt from the priority-1 authentication check. When role headers are
present, the role must still be ProgramAdmin (priority 2 applies to all).
"""
from flask import Blueprint, request

import clock
import services
from errors import raise_err, ERR_FORBIDDEN_ROLE
from util import body_json, parse_iso_datetime, success_object
from errors import ERR_INVALID_REQUEST

bp = Blueprint("clock", __name__)


@bp.post("/awards/_clock/set_current_utc")
def set_clock():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID") or "system"
    if role is not None and role != "ProgramAdmin":
        raise_err(ERR_FORBIDDEN_ROLE, "Only ProgramAdmin may set the clock")
    body = body_json()
    raw = body.get("to_iso8601")
    dt = parse_iso_datetime(raw)
    if dt is None:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 datetime")
    clock.set_current(dt)
    services.run_clock_sweep(actor_role=role or "system", actor_id=uid)
    return success_object({"current_utc": raw}, 200)
