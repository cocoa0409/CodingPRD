"""Audit log listing endpoint."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import require_auth
from ..response import list_envelope
from ..store import store
from ..utils import page_slice, parse_pagination


audit_bp = Blueprint("audit_logs", __name__)


@audit_bp.route("/audit-logs", methods=["GET"])
@require_auth(["PlatformAdmin", "EditorInChief"])
def list_audit_logs():
    limit, offset = parse_pagination()
    entity = request.args.get("entity")
    entity_id = request.args.get("entity_id")
    action = request.args.get("action")
    rows = sorted(store.audit_logs, key=lambda r: r["created_at"])
    if entity:
        rows = [r for r in rows if r.get("entity") == entity]
    if entity_id:
        rows = [r for r in rows if r.get("entity_id") == entity_id]
    if action:
        rows = [r for r in rows if r.get("action") == action]
    page, total = page_slice(rows, limit, offset)
    return list_envelope(page, total=total, limit=limit, offset=offset)
