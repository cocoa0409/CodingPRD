"""Ops cycle and logical clock endpoints."""

from core import (
    db, get_caller, require_role, get_body, ok, field_datetime,
)
from billing import run_cycle


def register(app):

    @app.route("/ops/run-cycle", methods=["POST"])
    def ops_run_cycle():
        get_body()
        caller = get_caller()
        require_role(caller, {"PlatformAdmin"})
        summary = run_cycle()
        return ok(summary)

    @app.route("/_clock/set_current_utc", methods=["POST"])
    def set_clock():
        body = get_body()
        to_dt = field_datetime(body, "to_iso8601", required=True)
        caller = get_caller()
        require_role(caller, {"PlatformAdmin"})
        db.clock = to_dt
        return ok({})
