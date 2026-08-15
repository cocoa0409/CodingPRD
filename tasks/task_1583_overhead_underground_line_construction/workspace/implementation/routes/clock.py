"""Logical clock endpoint (PRD 2.5): POST /_clock/set_current_utc.

Startup default is exactly 2026-08-01T00:00:00Z; the clock never falls back to
wall-clock time. Setting the clock re-evaluates outage windows (lazy
IN_EFFECT) and crew/equipment computed statuses (derived on read)."""
from flask import Blueprint

from middleware import authorized, ALL_ROLES
from response import success_object
from services.core import sweep_outages_in_effect
from util import CLOCK
from validate import get_body, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorized(list(ALL_ROLES))
    body = get_body()
    to_iso8601 = req_datetime(body, "to_iso8601")
    CLOCK.set(to_iso8601)
    sweep_outages_in_effect()
    return success_object({})
