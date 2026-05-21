"""Clock advance endpoint."""

from __future__ import annotations

from auth import require_role
from clock import CLOCK
from dispatch_engine import sweep_offer_timeouts
from envelope import success
from errors import APIError
from store import STORE
from validation import get_body


def register(app):
    @app.post("/api/_clock/advance")
    def advance_clock():
        require_role({"PlatformAdmin"})
        body = get_body()
        if "seconds" not in body:
            raise APIError("ERR_VALIDATION", "'seconds' is required.")
        seconds = body["seconds"]
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
            raise APIError("ERR_VALIDATION", "'seconds' must be numeric.")
        if seconds < 0:
            raise APIError("ERR_VALIDATION", "'seconds' must be non-negative.")

        with STORE.lock:
            CLOCK.advance(float(seconds))
            sweep_offer_timeouts()

        return success({"advanced_seconds": float(seconds), "now": CLOCK.now_iso()})
