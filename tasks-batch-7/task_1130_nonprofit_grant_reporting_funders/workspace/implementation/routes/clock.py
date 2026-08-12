"""Test-driving logical clock endpoint."""

import db
import services as S
from middleware import actor, body, require_roles
from response import ok
from util import fmt_dt, get_dt


def set_clock():
    _, role = actor()
    require_roles(role, {"SystemAdmin"})
    data = body()
    to = get_dt(data, "to_iso8601")
    db.set_now(to)
    S.fire_clock_transitions()
    return ok({"current_utc": fmt_dt(db.now())})


def register(app):
    app.add_url_rule("/_clock/set_current_utc", "clock_set", set_clock, methods=["POST"])
