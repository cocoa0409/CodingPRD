"""Rejection-record routes."""
from __future__ import annotations

from flask import Flask, request

from ..auth import require_auth
from ..pagination import parse_limit_offset
from ..services.serializers import serialize_rejection
from ..store import get_store
from ._helpers import ok_list, with_lock


def register(app: Flask) -> None:
    @app.get("/customs/rejection-records")
    @require_auth("SystemAdmin", "BrokerOps", "DeclarationOfficer")
    @with_lock
    def _list_rejections():
        limit, offset = parse_limit_offset()
        rejection_reason_code = request.args.get("rejection_reason_code")
        declaration_id = request.args.get("declaration_id")
        items = list(get_store().rejection_records.values())
        if rejection_reason_code is not None:
            items = [
                r for r in items if r.get("rejection_reason_code") == rejection_reason_code
            ]
        if declaration_id is not None:
            items = [r for r in items if r.get("declaration_id") == declaration_id]
        items.sort(key=lambda r: r.get("created_at") or "")
        return ok_list([serialize_rejection(r) for r in items], limit, offset)
