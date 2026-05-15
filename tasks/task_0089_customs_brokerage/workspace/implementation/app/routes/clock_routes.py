"""Test-driving clock route."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..services import clock_ops
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:
    @app.post("/customs/_clock/advance")
    @require_auth("SystemAdmin")
    @with_lock
    def _advance_clock():
        body = get_json_body()
        result = clock_ops.advance_clock(body)
        return ok(result)
