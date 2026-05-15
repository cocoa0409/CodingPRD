"""AuditLog list endpoint."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import require_auth
from ..response import list_envelope
from ..store import store
from ..utils import page_slice, parse_pagination
from ._helpers import get_org_or_404


audit_log_bp = Blueprint("audit_log", __name__)


@audit_log_bp.route("/organizations/<org_id>/audit-log", methods=["GET"])
@require_auth(["PlatformAdmin", "Verifier"])
def list_audit(org_id):
    get_org_or_404(org_id)
    limit, offset = parse_pagination()
    event_type_f = request.args.get("event_type")
    target_entity_f = request.args.get("target_entity")
    items = [
        r for r in store.audit_logs
        if r.get("organization_id") == org_id
        and (event_type_f is None or r.get("event_type") == event_type_f)
        and (target_entity_f is None or r.get("target_entity") == target_entity_f)
    ]
    items.sort(key=lambda x: (x.get("created_at", ""), x.get("id", "")))
    page, total = page_slice(items, limit, offset)
    return list_envelope(page, total, limit, offset)
