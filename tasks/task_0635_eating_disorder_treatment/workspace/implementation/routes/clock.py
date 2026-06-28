"""Logical clock endpoint (PRD §2.4)."""
from flask import Blueprint

import errors
from db import store
from clock import parse_iso
from errors import ApiError
from middleware import require_auth_and_roles
from response import success
from services.common import get_json_body, require_field
from services.domain import reevaluate_authorizations_after_clock_change

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_auth_and_roles(["Admin"])
def set_clock():
    body = get_json_body()
    to_iso = require_field(body, "to_iso8601")
    try:
        dt = parse_iso(to_iso)
    except (ValueError, TypeError):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "to_iso8601 must be a valid ISO 8601 instant.")

    with store.lock:
        store.clock.set(dt)
        # Advancing the clock re-evaluates authorization expiry/exhaustion and
        # may cascade admissions to DISCHARGE_PENDING (PRD §2.4, §3.11).
        reevaluate_authorizations_after_clock_change()

    # PRD endpoint output: null (no data). 200 OK with empty object data.
    return success({}, status=200, response_type="object")
