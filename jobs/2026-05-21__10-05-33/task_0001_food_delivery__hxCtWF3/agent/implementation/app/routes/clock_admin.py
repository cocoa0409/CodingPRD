"""PlatformAdmin clock advance — sweeps 60-second offer timeouts."""
from flask import request

from ..auth import parse_headers, require_role
from ..envelope import success
from ..errors import fail
from ..server import clock


def register(app, prefix):
    app.add_url_rule("/api/_clock/advance", endpoint=f"{prefix}.advance", view_func=advance, methods=["POST"])


def advance():
    parse_headers()
    require_role("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    seconds = body.get("seconds")
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or seconds < 0:
        raise fail("ERR_VALIDATION", "seconds must be a non-negative number")
    clock.advance(seconds)
    from ..services.dispatch import sweep_offer_timeouts
    swept = sweep_offer_timeouts()
    return success({"advanced_seconds": seconds, "swept_offers": swept})
