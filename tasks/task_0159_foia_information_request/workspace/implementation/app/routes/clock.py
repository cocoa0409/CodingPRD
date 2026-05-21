"""/foia/_clock and /foia/_sweep — test-driving endpoints."""

from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..envelope import ok_object
from ..errors import ApiError, ERR_INVALID_INPUT
from ..services.sweep import run_sweep
from ..timeutil import clock, iso_now, parse_iso
from ..util import require_json_body, require_str


clock_bp = Blueprint("clock", __name__)


@clock_bp.post("/foia/_clock/advance")
@require_auth({"ClockOperator"})
def advance():
    payload = require_json_body()
    to_iso = require_str(payload, "to_iso_datetime", max_len=64)
    try:
        target = parse_iso(to_iso)
    except Exception:
        raise ApiError(ERR_INVALID_INPUT, 400, "Invalid ISO datetime.")
    new_time = clock.advance_to(target)
    promoted = run_sweep()
    return ok_object(
        {
            "now": iso_now(new_time),
            "promoted_notices": promoted,
        }
    )


@clock_bp.post("/foia/_sweep/run")
@require_auth({"ClockOperator"})
def sweep():
    promoted = run_sweep()
    return ok_object(
        {
            "now": iso_now(clock.now()),
            "promoted_notices": promoted,
        }
    )


@clock_bp.get("/foia/_clock")
@require_auth({"ClockOperator", "Officer"})
def get_clock():
    return ok_object({"now": iso_now(clock.now())})
