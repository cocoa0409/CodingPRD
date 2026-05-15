"""Test-only event-emit endpoint."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..errors import ApiError
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:
    app.add_url_rule(
        "/_events/emit",
        view_func=require_auth("CDCSupervisor")(with_lock(emit_event)),
        methods=["POST"],
    )


def emit_event():
    body = get_json_body()
    source = body.get("source")
    payload = body.get("payload")
    if not source or payload is None:
        raise ApiError("ERR_INVALID_INPUT", "Missing source or payload.")
    # We acknowledge the event but do not fan out into changes here; the platform
    # provides explicit endpoints for ingesting contact events and results.
    return ok({"acknowledged": True, "source": source, "payload": payload})
