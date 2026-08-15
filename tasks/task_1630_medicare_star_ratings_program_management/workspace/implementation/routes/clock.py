"""Logical clock endpoint (StarsAdmin only)."""
from db import LOGICAL_CLOCK
from middleware import auth
from response import ok
from util import as_iso_dt, body, format_iso, parse_dt, required


def register(app):
    @app.route("/api/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        auth(["StarsAdmin"])
        data = body()
        to_iso8601 = as_iso_dt(required(data, "to_iso8601"), "to_iso8601")
        LOGICAL_CLOCK["current"] = format_iso(parse_dt(to_iso8601))
        return ok({"now": LOGICAL_CLOCK["current"]})
