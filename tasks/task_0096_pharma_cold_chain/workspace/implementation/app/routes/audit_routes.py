"""Audit log list endpoint."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..errors import ApiError
from ..pagination import parse_filter, parse_limit_offset
from ..response import paginate
from ..store import get_store
from ._helpers import list_ok


def register(app: Flask) -> None:
    @app.route("/warehouses/<wid>/audit-log", methods=["GET"])
    @require_auth("WarehouseAdmin", "QAOfficer", "RecallOfficer")
    def list_audit(wid: str):
        store = get_store()
        if wid not in store.warehouses:
            raise ApiError("ERR_NOT_FOUND", "Warehouse not found")
        limit, offset = parse_limit_offset()
        action_f = parse_filter("action")
        role_f = parse_filter("actor_role")
        items = [a for a in store.audit_entries.values() if a["warehouse_id"] == wid]
        if action_f is not None:
            items = [a for a in items if a["action"] == action_f]
        if role_f is not None:
            items = [a for a in items if a["actor_role"] == role_f]
        items.sort(key=lambda a: a["created_at"])
        sliced, page = paginate(items, limit, offset)
        return list_ok(sliced, page)
