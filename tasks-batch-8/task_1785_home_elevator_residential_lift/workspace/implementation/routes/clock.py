"""Logical clock test-driving endpoint (PRD 2.4). Setting the clock applies all
time-derived sweeps atomically with the set."""

from flask import Blueprint

import db
from middleware import DEALER_ADMIN, require_roles
from response import ok
from services import cascade
from util import fmt_dt, get_json_body, validate_body

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
@require_roles(DEALER_ADMIN)
def set_current_utc():
    vals = validate_body(get_json_body(), {"to_iso8601": ("datetime", True, None)})
    db.set_clock(vals["to_iso8601"])
    cascade.run_clock_sweeps()
    return ok({"current_utc": fmt_dt(db.now())})
