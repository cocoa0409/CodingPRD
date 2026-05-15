"""Clock and sweeper endpoints."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..services import clock_ops as svc
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:

    @app.post("/_clock/advance")
    @require_auth("LeagueAdmin")
    @with_lock
    def advance_clock():
        body = get_json_body()
        return ok(svc.advance_clock(body))

    @app.post("/_sweep/run")
    @require_auth("LeagueAdmin")
    @with_lock
    def run_sweeper():
        return ok(svc.run_sweeper())
