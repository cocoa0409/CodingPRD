"""POST /_clock/advance"""
from flask import Flask

from ..auth import require_auth
from ..clock import CLOCK, format_iso, parse_iso
from ..errors import ApiError
from ..services.clock_advance import advance_clock
from ._helpers import get_json_body, ok


def register(app: Flask) -> None:
    @app.route("/_clock/advance", methods=["POST"])
    @require_auth("ServicerAdmin", "SystemTest")
    def clock_advance():
        body = get_json_body()
        to = body.get("to")
        if not to:
            raise ApiError("ERR_INVALID_INPUT", "Missing 'to' field.")
        try:
            new_now = parse_iso(to)
        except Exception:
            raise ApiError("ERR_INVALID_INPUT", f"Invalid 'to' timestamp: {to!r}")
        advance_clock(new_now)
        return ok({"now": format_iso(CLOCK.now)})
