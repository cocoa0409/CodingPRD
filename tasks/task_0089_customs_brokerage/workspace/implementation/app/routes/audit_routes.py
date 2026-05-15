"""Audit log routes."""
from __future__ import annotations

from flask import Flask, request

from ..auth import require_auth
from ..pagination import parse_limit_offset
from ..services.serializers import serialize_audit
from ..store import get_store
from ._helpers import ok_list, with_lock


def register(app: Flask) -> None:
    @app.get("/customs/audit-log")
    @require_auth("SystemAdmin", "BrokerOps")
    @with_lock
    def _list_audit_log():
        limit, offset = parse_limit_offset()
        entity_type = request.args.get("entity_type")
        entity_id = request.args.get("entity_id")
        event_type = request.args.get("event_type")
        items = list(get_store().audit_log.values())
        if entity_type is not None:
            items = [a for a in items if a.get("entity_type") == entity_type]
        if entity_id is not None:
            items = [a for a in items if a.get("entity_id") == entity_id]
        if event_type is not None:
            items = [a for a in items if a.get("event_type") == event_type]
        items.sort(key=lambda a: a.get("created_at") or "")
        return ok_list([serialize_audit(a) for a in items], limit, offset)
