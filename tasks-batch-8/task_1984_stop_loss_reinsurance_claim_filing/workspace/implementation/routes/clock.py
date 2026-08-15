"""Logical clock test-driving endpoint (PRD §2.10).

Startup default is exactly 2026-08-01T00:00:00Z; the clock is only ever moved
by this endpoint and never falls back to wall-clock time. Advancing (or
re-setting) the clock fires the IN_FORCE -> EXPIRED contract transition for any
contract whose policy_year_end the new instant has reached.
"""
from flask import Blueprint

from middleware import authorized
from response import success_object
from routes.contracts import expire_contracts_up_to
from util import CLOCK
from validate import get_body, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/stop-loss/_clock/set_current_utc")
def set_clock():
    authorized(["PlanAdministrator"])
    body = get_body()
    to_iso8601 = req_datetime(body, "to_iso8601")
    new_now = CLOCK.set(to_iso8601)
    expire_contracts_up_to(new_now)
    return success_object({})
