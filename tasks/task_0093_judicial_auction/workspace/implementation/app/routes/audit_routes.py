"""Audit event listing — CourtClerk only."""
from __future__ import annotations

from flask import Flask, request

from ..auth import require_auth
from ..clock import parse_iso
from ..errors import ApiError
from ..pagination import parse_limit_offset
from ..store import get_store
from ._helpers import ok_list, with_lock


def register(app: Flask) -> None:
    @app.route("/audit-events", methods=["GET"])
    @require_auth("CourtClerk")
    @with_lock
    def _list_events():
        store = get_store()
        items = list(store.audit_events.values())

        subject_entity = request.args.get("subject_entity")
        if subject_entity:
            items = [e for e in items if e.get("subject_entity") == subject_entity]
        subject_id = request.args.get("subject_id")
        if subject_id:
            items = [e for e in items if e.get("subject_id") == subject_id]
        kind = request.args.get("kind")
        if kind:
            items = [e for e in items if e.get("kind") == kind]

        since = request.args.get("since")
        until = request.args.get("until")
        if since:
            try:
                since_dt = parse_iso(since)
            except ValueError as exc:
                raise ApiError("ERR_VALIDATION", str(exc))
            items = [
                e for e in items
                if e.get("created_at") and parse_iso(e["created_at"]) >= since_dt
            ]
        if until:
            try:
                until_dt = parse_iso(until)
            except ValueError as exc:
                raise ApiError("ERR_VALIDATION", str(exc))
            items = [
                e for e in items
                if e.get("created_at") and parse_iso(e["created_at"]) <= until_dt
            ]

        items.sort(key=lambda r: r.get("created_at") or "")
        limit, offset = parse_limit_offset()
        return ok_list(items, limit, offset)
