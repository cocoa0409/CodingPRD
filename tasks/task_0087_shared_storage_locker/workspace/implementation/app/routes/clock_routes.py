"""Test-driver clock and sweep endpoints."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..services import clock_ops as svc
from ..store import LOCK, reset_store
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:
    @app.post("/_clock/advance")
    @require_auth("Operator")
    @with_lock
    def advance_clock():
        return ok(svc.advance_clock(get_json_body()))

    @app.post("/_sweep/run")
    @require_auth("Operator")
    @with_lock
    def run_sweep():
        return ok(svc.run_sweep())

    @app.post("/__test__/reset")
    def test_reset():
        # Test-infrastructure extension: wipe in-memory state between tests.
        # No auth required — purely a benchmark-driver convenience.
        with LOCK:
            reset_store()
        return ok({"reset": True})
