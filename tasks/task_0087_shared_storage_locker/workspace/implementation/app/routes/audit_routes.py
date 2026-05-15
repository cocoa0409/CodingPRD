"""Audit-event routes."""
from __future__ import annotations

from flask import Flask, request

from ..auth import require_auth
from ..pagination import parse_limit_offset
from ..services import audit_revenue as svc
from ._helpers import ok_list, with_lock


def register(app: Flask) -> None:
    @app.get("/audit-events")
    @require_auth("Operator")
    @with_lock
    def list_audit_events():
        event_kind = request.args.get("event_kind")
        subject_id = request.args.get("subject_id")
        subject_type = request.args.get("subject_type")
        actor_id = request.args.get("actor_id")
        from_ts = request.args.get("occurred_at_from")
        to_ts = request.args.get("occurred_at_to")
        limit, offset = parse_limit_offset()
        items = svc.list_audit_events(event_kind, subject_id, subject_type, actor_id, from_ts, to_ts)
        return ok_list(items, limit, offset)
