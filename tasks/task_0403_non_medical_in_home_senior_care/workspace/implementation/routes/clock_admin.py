"""Test-only logical clock endpoint (PRD §2.12)."""
from flask import Blueprint

import clock
from middleware import get_auth, require_roles
from response import success
from services import requtil

bp = Blueprint("clock_admin", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _, role = get_auth()
    require_roles(role, {"AgencyAdmin"})
    body = requtil.get_body()
    dt = requtil.require_datetime(body, "to_iso8601")
    clock.set_current_utc(dt)
    # Performs no state-machine transition and returns no resource body.
    return success({}, status=200)
