"""Audit log endpoint."""
from __future__ import annotations

from flask import Flask, request

from ..auth import require_auth
from ..pagination import parse_limit_offset
from ..store import get_store
from ._helpers import ok_list, with_lock


def register(app: Flask) -> None:

    @app.get("/audit-log")
    @require_auth("LeagueAdmin")
    @with_lock
    def list_audit_log():
        subject_type = request.args.get("subject_type")
        subject_id = request.args.get("subject_id")
        actor_user_id = request.args.get("actor_user_id")
        limit, offset = parse_limit_offset()
        rows = list(get_store().audit_logs.values())
        if subject_type is not None:
            rows = [r for r in rows if r["subject_type"] == subject_type]
        if subject_id is not None:
            rows = [r for r in rows if r["subject_id"] == subject_id]
        if actor_user_id is not None:
            rows = [r for r in rows if r["actor_user_id"] == actor_user_id]
        rows.sort(key=lambda r: (r["created_at"], r["id"]))
        return ok_list([dict(r) for r in rows], limit, offset)
