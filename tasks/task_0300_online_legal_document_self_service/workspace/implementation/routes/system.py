"""Test-driving system endpoints: logical clock + reminder dispatch sweep."""

from flask import Blueprint

import validators
from common import parse_datetime, touch
from db import store
from middleware import get_json_body, roles
from response import empty_response

bp = Blueprint("system", __name__)


@bp.route("/legal/_clock/set", methods=["POST"])
@roles("PlatformAdmin")
def set_clock():
    body = get_json_body()
    to_iso = validators.require_string(body, "to_iso8601")
    # Validate it parses (raises ERR_INVALID_REQUEST otherwise).
    parse_datetime(to_iso, "to_iso8601")
    store.clock_now = to_iso
    return empty_response(200)


@bp.route("/legal/_reminders/dispatch_due", methods=["POST"])
@roles("PlatformAdmin")
def dispatch_due():
    # Determine the comparison instant: logical clock if set, else wall clock.
    if store.clock_now is not None:
        now_dt = parse_datetime(store.clock_now, "clock")
    else:
        from db import now_iso
        now_dt = parse_datetime(now_iso(), "now")

    # Sweep every SCHEDULED reminder whose due_at <= now -> SENT (deterministic).
    reminders = [
        rm for rm in store.update_reminders.values()
        if rm["status"] == "SCHEDULED"
    ]
    reminders.sort(key=lambda rm: rm["_seq"])
    for rm in reminders:
        due = parse_datetime(rm["due_at"], "due_at")
        if due <= now_dt:
            rm["status"] = "SENT"
            touch(rm)

    return empty_response(200)
