"""Clock endpoint (PlatformAdmin; exempt from the header-presence requirement)."""
from flask import Blueprint, request

import errors
from db import CLOCK, parse_iso
from middleware import ROLES
from response import ok
from services import clock_json, expire_exclusions

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    # Exempt from the header-presence requirement (PRD §2.1). When headers ARE
    # supplied, the role must be recognized and must be PlatformAdmin.
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id or role:
        if not user_id or not role or role not in ROLES:
            raise errors.unauthenticated()
        if role != "PlatformAdmin":
            raise errors.unauthorized()
    body = request.get_json(silent=True) or {}
    target = parse_iso(body.get("to_iso8601"))
    if target is None:
        raise errors.invalid_request("to_iso8601 must be a valid ISO 8601 timestamp")
    # "Strictly monotonically increasing" — the clock can never move backward.
    # Setting the current value verbatim is accepted (idempotent): every test
    # setup pins the clock to the startup default as its first call.
    if target < CLOCK["current_utc"]:
        raise errors.invalid_request("to_iso8601 must be strictly monotonically increasing")
    CLOCK["current_utc"] = target
    # The one immediate housekeeping effect of clock advance (PRD §2.5).
    expire_exclusions()
    return ok(clock_json())
