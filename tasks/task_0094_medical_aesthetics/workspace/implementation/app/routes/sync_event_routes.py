"""SyncEvent listing (read-only outbox)."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..pagination import parse_limit_offset, parse_optional_str
from ..response import paginate
from ..store import get_store
from ._helpers import list_ok


def register(app: Flask) -> None:
    @app.route("/aesthetics/sync-events", methods=["GET"])
    @require_auth("MedicalDirector", "FinanceOfficer")
    def list_sync():
        limit, offset = parse_limit_offset()
        topic = parse_optional_str("topic")
        kind = parse_optional_str("kind")
        items = list(get_store().sync_events.values())
        if topic:
            items = [e for e in items if e["topic"] == topic]
        if kind:
            items = [e for e in items if e["kind"] == kind]
        items.sort(key=lambda x: x["created_at"])
        sliced, page = paginate(items, limit, offset)
        return list_ok(sliced, page)
