"""External event ingestion (test/automation only)."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..errors import ApiError
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:
    @app.route("/_events/emit", methods=["POST"])
    @require_auth("AuctionAdmin")
    @with_lock
    def _emit():
        body = get_json_body()
        source = body.get("source")
        kind = body.get("kind")
        payload = body.get("payload")
        if not isinstance(source, str) or not source.strip():
            raise ApiError("ERR_VALIDATION", "source must be a non-empty string.")
        if not isinstance(kind, str) or not kind.strip():
            raise ApiError("ERR_VALIDATION", "kind must be a non-empty string.")
        if payload is not None and not isinstance(payload, dict):
            raise ApiError("ERR_VALIDATION", "payload must be an object.")
        # Stub: route to internal handler — for test purposes we just acknowledge.
        return ok({"accepted": True, "source": source, "kind": kind}, 202)
