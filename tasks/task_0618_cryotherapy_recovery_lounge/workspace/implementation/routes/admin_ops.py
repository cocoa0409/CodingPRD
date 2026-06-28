"""Test-driving endpoints: logical clock and recurring billing (PRD §2.4, §3.4)."""

from flask import Blueprint

import errors
from clock import clock, parse_iso8601, format_iso8601_ms
from helpers import get_body, require_field
from middleware import require_roles
from response import success
from services.billing import run_billing

bp = Blueprint("admin_ops", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_clock():
    body = get_body()
    raw = require_field(body, "to_iso8601")
    try:
        instant = parse_iso8601(raw)
    except ValueError:
        raise errors.invalid_request("to_iso8601 must be an ISO 8601 instant")
    clock.set(instant)
    return success({"current_utc": format_iso8601_ms(clock.now())}, 200)


@bp.post("/_billing/run")
@require_roles("PlatformAdmin")
def billing_run():
    result = run_billing()
    return success(result, 200)
