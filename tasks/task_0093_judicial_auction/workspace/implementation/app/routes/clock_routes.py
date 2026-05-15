"""Test-driving clock-advance endpoint."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..clock import now_iso_ms
from ..errors import ApiError
from ..services.time_machine import advance_clock_to
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:
    @app.route("/_clock/advance", methods=["POST"])
    @require_auth("AuctionAdmin", "CourtClerk")
    @with_lock
    def _advance():
        body = get_json_body()
        to_iso = body.get("to")
        if not isinstance(to_iso, str) or not to_iso.strip():
            raise ApiError("ERR_VALIDATION", "to must be a non-empty ISO 8601 string.")
        advance_clock_to(to_iso)
        return ok({"now": now_iso_ms()}, 200)

    @app.route("/_clock/now", methods=["GET"])
    def _now():
        # Test-harness read of the simulated server clock. Not part of
        # the PRD surface; allows fixtures to anchor schedules to the
        # server's "now" instead of wall time.
        return {"meta": {}, "response_type": "object", "data": {"now": now_iso_ms()}}, 200
