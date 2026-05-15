"""External sync events list endpoint."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..errors import ApiError
from ..pagination import parse_filter, parse_limit_offset
from ..response import paginate
from ..store import get_store
from ._helpers import list_ok


def register(app: Flask) -> None:
    @app.route("/warehouses/<wid>/external-events", methods=["GET"])
    @require_auth("WarehouseAdmin", "RecallOfficer", "QAOfficer")
    def list_external_events(wid: str):
        store = get_store()
        if wid not in store.warehouses:
            raise ApiError("ERR_NOT_FOUND", "Warehouse not found")
        limit, offset = parse_limit_offset()
        target_f = parse_filter("target_system")
        type_f = parse_filter("event_type")
        items = [e for e in store.external_events.values() if e["warehouse_id"] == wid]
        if target_f is not None:
            items = [e for e in items if e["target_system"] == target_f]
        if type_f is not None:
            items = [e for e in items if e["event_type"] == type_f]
        items.sort(key=lambda e: e["created_at"])
        sliced, page = paginate(items, limit, offset)
        return list_ok(sliced, page)
