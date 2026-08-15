"""Logical clock route (PRD 2.4)."""

from flask import Blueprint

import util
import clock
from db import iso_from_dt, store
from middleware import require_roles
from response import success_object
from services import core

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("AthleticsAdmin")
    body = util.get_json_body()
    to = util.require_iso(body, "to_iso8601")
    clock.set_now(to)
    # PRD 2.9: weekly_prime_hours_used ALWAYS reflects the prime load of the
    # week containing the logical clock's date. Moving the clock shifts that
    # week, so every facility's display counter is reconciled here (the
    # recompute touches no version/updated_at, matching permit mutations).
    for facility in store.facilities.values():
        core.recompute_facility_weekly_prime(facility)
    return success_object({"current_utc": iso_from_dt(clock.now())})
