"""Logical clock endpoint."""
from db import LOGICAL_CLOCK
from middleware import ALL_ROLES, auth
from response import ok
from services import run_global_sweeps
from util import as_iso_dt, body, parse_dt, format_iso, required


def register(app):
    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        auth(ALL_ROLES)
        data = body()
        to_iso8601 = as_iso_dt(required(data, "to_iso8601"), "to_iso8601")
        dt = parse_dt(to_iso8601)
        LOGICAL_CLOCK["current"] = format_iso(dt)
        run_global_sweeps()
        return ok({"current_utc": LOGICAL_CLOCK["current"]})
