"""POST /_clock/set_current_utc -- the logical clock and its two-step sweep."""

from datetime import timedelta

from flask import Blueprint

import store
from constants import CHRONIC_LAPSE_GRACE_DAYS
from envelope import ok
from ladder import Ctx
from timeutil import parse_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    ctx = Ctx(roles=("HealthServicesAdmin",))
    ctx.require("to_iso8601")
    ctx.check_type("to_iso8601", "datetime")
    ctx.run()

    new_clock = parse_dt(ctx.body.get("to_iso8601"))
    store.set_clock(new_clock)

    # Sweep step 1 -- overdue intake screenings.
    for row in store.sort_rows([s for s in store.intake_screenings.values()
                                if s["status"] == "PENDING"]):
        if row["due_at"].dt < new_clock:
            row["status"] = "OVERDUE"
            store.touch(row)

    # Sweep step 2 -- runs only after step 1 has finished.
    grace = timedelta(days=CHRONIC_LAPSE_GRACE_DAYS)
    for row in store.sort_rows([e for e in store.chronic_enrollments.values()
                                if e["status"] == "ACTIVE"]):
        due = row.get("next_due_date")
        if due is not None and (due.dt + grace) < new_clock:
            row["status"] = "LAPSED"
            store.touch(row)

    return ok({})
