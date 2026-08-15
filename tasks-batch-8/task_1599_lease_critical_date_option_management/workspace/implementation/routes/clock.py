"""Logical clock endpoint (PRD §2.4)."""
from flask import Blueprint

from middleware import authorized
from response import success_object
from services.core import new_record, serialize_clock_event
from services.sweep import run_clock_sweep
from util import CLOCK, fmt_dt, is_valid_dateish
from validate import get_body, req_str
from errors import raise_error, ERR_VALIDATION

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorized(["PlatformAdmin"])
    body = get_body()
    to_iso8601 = req_str(body, "to_iso8601")
    if not is_valid_dateish(to_iso8601):
        raise_error(ERR_VALIDATION, "to_iso8601 must be a valid ISO 8601 instant")
    new_dt = CLOCK.set(to_iso8601)
    fired, lapsed, holdover = run_clock_sweep(new_dt)
    event = new_record("clock_events", {
        "set_to": fmt_dt(new_dt),
        "fired_reminder_ids": fired,
        "lapsed_option_ids": lapsed,
        "holdover_lease_ids": holdover,
    }, common=False)
    return success_object(serialize_clock_event(event), 201)
