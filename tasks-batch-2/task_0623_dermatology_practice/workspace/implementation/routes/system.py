"""Administrative test-driving endpoints: logical clock and recall sweep."""
from flask import Blueprint

import clock
import db
import helpers
import response
from middleware import require

bp = Blueprint("system", __name__)


@bp.post("/_clock/set_current_utc")
@require("PracticeAdmin")
def set_clock():
    data = helpers.body()
    helpers.require_fields(data, "to_iso8601")
    dt = helpers.parse_dt(data["to_iso8601"], "to_iso8601")
    clock.set_now(dt)
    # PRD 4: clock-set returns 200 OK; no resource data.
    return response.ok({})


@bp.post("/_recall/sweep")
@require("PracticeAdmin", "FrontDesk")
def recall_sweep():
    """Fire all PENDING reminders whose due_at <= clock now: PENDING -> SENT.

    A reminder whose due_at is still in the future is skipped, not errored.
    Returns the swept reminders.
    """
    now = clock.now()
    swept = []
    for r in helpers.sort_created(list(db.recall_reminders.values())):
        if r["status"] != "PENDING":
            continue
        due = helpers.parse_dt(r["due_at"])
        if now >= due:
            r["status"] = "SENT"
            db.touch(r)
            swept.append(r)
    # The sweep returns an array of the swept reminders.
    return response.listing(swept, limit=len(swept), offset=0, total_count=len(swept))
