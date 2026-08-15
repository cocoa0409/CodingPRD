"""Test-driving logical clock: POST /coop/_clock/set_current_utc.

Setting the clock triggers the expiry sweep: every REQUESTED harvest ticket
whose window_start lies before the new current time moves to EXPIRED.
"""
from flask import Blueprint

import db
from db import store, touch
from middleware import authenticate, require_roles
from response import ok
from validation import get_body, parse_datetime_value

bp = Blueprint("misc", __name__)


@bp.post("/coop/_clock/set_current_utc")
def set_current_utc():
    body = get_body()
    target = parse_datetime_value(body.get("to_iso8601"), "to_iso8601")
    _, role = authenticate()
    require_roles(role, {"CoopAdmin"})

    db.LOGICAL_CLOCK = target
    for ticket in store.tickets.values():
        if ticket["status"] == "REQUESTED" and ticket["window_start"] < target:
            ticket["status"] = "EXPIRED"
            touch(ticket)

    return ok({"current_utc": db.iso_dt(target)})
