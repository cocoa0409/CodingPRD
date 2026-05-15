"""External event emission route."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..services import events
from ..services.serializers import serialize_external_event
from ._helpers import get_json_body, ok, with_lock


def register(app: Flask) -> None:
    @app.post("/customs/_events/emit")
    @require_auth("SystemAdmin")
    @with_lock
    def _emit():
        body = get_json_body()
        record = events.emit_event(body)
        return ok(serialize_external_event(record), status=202)
