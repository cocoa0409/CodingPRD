"""Test-only clock endpoint (PRD §2.11)."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..clock import CLOCK, format_iso, parse_iso
from ..errors import ApiError
from ._helpers import get_json_body, ok


def register(app: Flask) -> None:
    @app.route("/_clock/advance", methods=["POST"])
    @require_auth("TestHarness", "Biller", "RegistrationClerk")
    def advance_clock():
        body = get_json_body()
        to_ts = body.get("to_timestamp")
        if not isinstance(to_ts, str) or not to_ts:
            raise ApiError("ERR_INVALID_INPUT", "to_timestamp is required.")
        try:
            dt = parse_iso(to_ts)
        except ValueError as exc:
            raise ApiError("ERR_INVALID_INPUT", str(exc))
        CLOCK.set(dt)
        return ok({"now": format_iso(CLOCK.now)})
