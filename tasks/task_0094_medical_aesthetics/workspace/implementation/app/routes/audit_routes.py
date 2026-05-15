"""Audit-entry listing."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..pagination import parse_limit_offset, parse_optional_str
from ..response import paginate
from ..store import get_store
from ._helpers import list_ok


def register(app: Flask) -> None:
    @app.route("/aesthetics/audit-entries", methods=["GET"])
    @require_auth("MedicalDirector", "SeniorPhysician")
    def list_audit():
        limit, offset = parse_limit_offset()
        st = parse_optional_str("subject_type")
        sid = parse_optional_str("subject_id")
        action = parse_optional_str("action")
        items = list(get_store().audit_entries.values())
        if st:
            items = [e for e in items if e["subject_type"] == st]
        if sid:
            items = [e for e in items if e["subject_id"] == sid]
        if action:
            items = [e for e in items if e["action"] == action]
        items.sort(key=lambda x: x["created_at"])
        sliced, page = paginate(items, limit, offset)
        return list_ok(sliced, page)
