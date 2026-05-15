"""Audit log read endpoint (PRD §3.10)."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import require_auth
from ..errors import api_error
from ..response import list_envelope
from ..store import store
from ..utils import page_slice, parse_pagination

bp = Blueprint("audit_logs", __name__, url_prefix="/scf/audit-logs")


@bp.get("")
@require_auth(["PlatformAdmin", "ComplianceOfficer"])
def list_audit_logs():
    limit, offset = parse_pagination()
    entity_type = request.args.get("entity_type")
    entity_id = request.args.get("entity_id")
    action = request.args.get("action")
    since = request.args.get("since")

    items = list(store.audit_logs)
    if entity_type:
        items = [x for x in items if x.get("entity_type") == entity_type]
    if entity_id:
        items = [x for x in items if x.get("entity_id") == entity_id]
    if action:
        items = [x for x in items if x.get("action") == action]
    if since:
        items = [x for x in items if x.get("occurred_at", "") >= since]
    items.sort(key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    page, total = page_slice(items, limit, offset)
    return list_envelope(page, total, limit, offset)
