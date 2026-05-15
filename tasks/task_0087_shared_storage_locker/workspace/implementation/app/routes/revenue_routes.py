"""Revenue routes."""
from __future__ import annotations

from flask import Flask, request

from ..auth import require_auth
from ..pagination import parse_limit_offset
from ..services import audit_revenue as svc
from ._helpers import ok, ok_list, with_lock


def register(app: Flask) -> None:
    @app.get("/revenue-records")
    @require_auth("Operator")
    @with_lock
    def list_revenue_records():
        cabinet_id = request.args.get("cabinet_id")
        revenue_kind = request.args.get("revenue_kind")
        from_ts = request.args.get("occurred_at_from")
        to_ts = request.args.get("occurred_at_to")
        limit, offset = parse_limit_offset()
        items = svc.list_revenue_records(cabinet_id, revenue_kind, from_ts, to_ts)
        return ok_list(items, limit, offset)

    @app.get("/cabinets/<cabinet_id>/revenue-summary")
    @require_auth("Operator")
    @with_lock
    def revenue_summary(cabinet_id: str):
        from_ts = request.args.get("occurred_at_from")
        to_ts = request.args.get("occurred_at_to")
        return ok(svc.cabinet_revenue_summary(cabinet_id, from_ts, to_ts))
