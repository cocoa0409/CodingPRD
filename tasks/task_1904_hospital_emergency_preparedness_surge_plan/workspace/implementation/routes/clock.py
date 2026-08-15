"""Test-driving logical clock with scheduled sweeps."""

from flask import Blueprint

from db import clock, store
from envelope import success
from security import authorize
from util import field_dt, fmt_dt, require_body, touch

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@authorize(["PlatformAdmin"])
def set_clock():
    body = require_body()
    new_time = field_dt(body, "to_iso8601", required=True)
    clock.set(new_time)

    # Sweep 1: PENDING callbacks whose expires_at lies strictly before the new
    # clock time transition to EXPIRED. Equality survives the sweep.
    swept_callbacks = 0
    for cb in store["callback_requests"].values():
        if cb["status"] == "PENDING" and new_time > cb["expires_at"]:
            cb["status"] = "EXPIRED"
            touch(cb)
            swept_callbacks += 1

    # Sweep 2: OPEN / IN_PROGRESS improvement tasks strictly past their
    # due_date transition to OVERDUE. Equality survives the sweep.
    swept_tasks = 0
    for task in store["improvement_tasks"].values():
        if task["status"] in ("OPEN", "IN_PROGRESS") and new_time > task["due_date"]:
            task["status"] = "OVERDUE"
            touch(task)
            swept_tasks += 1

    return success({
        "current_utc": fmt_dt(clock.now()),
        "swept_callbacks": swept_callbacks,
        "swept_tasks": swept_tasks,
    }, "object", 200)
