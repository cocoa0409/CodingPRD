"""Audit log query endpoint."""
from __future__ import annotations

from flask import Flask, request

from ..auth import require_auth
from ..clock import parse_iso
from ..errors import ApiError
from ..pagination import parse_limit_offset
from ..store import get_store
from ._helpers import ok_list, with_lock


def register(app: Flask) -> None:
    app.add_url_rule(
        "/epi/audit-logs",
        view_func=require_auth("CDCSupervisor")(with_lock(list_audit)),
        methods=["GET"],
    )


def list_audit():
    store = get_store()
    entity_type = request.args.get("entity_type")
    entity_id = request.args.get("entity_id")
    since = request.args.get("since")
    until = request.args.get("until")
    limit, offset = parse_limit_offset()

    items = list(store.audit_logs.values())
    if entity_type:
        items = [a for a in items if a.get("entity_type") == entity_type]
    if entity_id:
        items = [a for a in items if a.get("entity_id") == entity_id]
    if since:
        try:
            s_dt = parse_iso(since)
            items = [a for a in items if parse_iso(a.get("at")) >= s_dt]
        except Exception:
            raise ApiError("ERR_INVALID_INPUT", f"Invalid since: {since!r}")
    if until:
        try:
            u_dt = parse_iso(until)
            items = [a for a in items if parse_iso(a.get("at")) <= u_dt]
        except Exception:
            raise ApiError("ERR_INVALID_INPUT", f"Invalid until: {until!r}")

    items.sort(key=lambda a: a.get("at", ""))
    return ok_list(items, limit, offset)
