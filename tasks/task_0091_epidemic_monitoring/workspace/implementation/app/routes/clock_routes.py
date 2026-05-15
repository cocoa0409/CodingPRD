"""Test-only clock-advance endpoint."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..clock import CLOCK, now_iso_ms
from ..errors import ApiError
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:
    app.add_url_rule(
        "/_clock/advance",
        view_func=require_auth("CDCSupervisor")(with_lock(advance_clock)),
        methods=["POST"],
    )


def advance_clock():
    body = get_json_body()
    seconds = body.get("seconds")
    if seconds is None:
        raise ApiError("ERR_INVALID_INPUT", "Missing seconds.")
    try:
        sec = float(seconds)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_INPUT", "seconds must be numeric.")
    CLOCK.advance(sec)
    return ok({"now": now_iso_ms(), "advanced_seconds": sec})
