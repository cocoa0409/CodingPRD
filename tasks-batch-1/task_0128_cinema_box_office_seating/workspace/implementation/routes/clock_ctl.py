"""Clock control endpoint (PRD §3.6, §3.9 / SCAFFOLD POST /_clock/advance).

Advancing the clock sets the server's logical current UTC instant and triggers a
sweep that EXPIRES every HELD order whose hold_expires_at has been reached/passed.
CinemaManager-only. Returns 200 with an empty data object (output: null).
"""
from __future__ import annotations

from flask import Blueprint

import clock
import errors as E
from middleware import authenticate, authorize, CINEMA_MANAGER
import response
from services import common as C
from services import domain as D

bp = Blueprint("clock_ctl", __name__)


@bp.route("/_clock/advance", methods=["POST"])
def clock_advance():
    role = authenticate()
    authorize(role, {CINEMA_MANAGER})
    body = C.get_body()
    C.require_fields(body, ["to_iso8601"])
    to_iso = body.get("to_iso8601")
    dt = C.parse_iso(to_iso)
    clock.set_clock(dt)
    # Sweep expiries against the new logical now.
    D.expire_sweep()
    return response.ok_object({}, 200)
