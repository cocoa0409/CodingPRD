"""/_clock test-driving endpoints."""

from __future__ import annotations

from flask import Blueprint

from ..auth import require_auth
from ..envelope import ok_object
from ..errors import ApiError, ERR_INVALID_INPUT
from ..services.exemptions import expire_crossed_exemptions
from ..timeutil import clock, iso_now, parse_iso
from ..util import require_json_body, require_str


clock_bp = Blueprint("clock", __name__)


@clock_bp.post("/_clock/advance")
@require_auth({"PlatformAdmin"})
def advance():
    payload = require_json_body()
    to_iso = require_str(payload, "to", max_len=64)
    try:
        target = parse_iso(to_iso)
    except Exception:
        raise ApiError(ERR_INVALID_INPUT, 400, "Invalid ISO datetime for 'to'.")

    prev = clock.now()
    new_time = clock.advance_to(target)
    expired = expire_crossed_exemptions(prev, new_time)
    return ok_object({"now": iso_now(new_time), "exemptions_expired": expired})


@clock_bp.get("/_clock")
@require_auth({"PlatformAdmin", "Driver", "CarrierSafetyOfficer", "FMCSAAuditor"})
def get_clock():
    return ok_object({"now": iso_now(clock.now())})
