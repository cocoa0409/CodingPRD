"""ComplianceAuditEvent list endpoint."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import ROLE_LAB_DIRECTOR, require_roles
from ..helpers import paginate, parse_pagination
from ..responses import listing
from ..services.serialize import audit_event_view
from ..store import store

bp = Blueprint("audit_events", __name__)


@bp.route("/audit-events", methods=["GET"])
@require_roles(ROLE_LAB_DIRECTOR)
def list_audit_events(**_):
    limit, offset = parse_pagination()
    lab_order_f = request.args.get("lab_order_id")
    event_type_f = request.args.get("event_type")
    items = list(store().audit_events.values())
    if lab_order_f:
        items = [r for r in items if r["lab_order_id"] == lab_order_f]
    if event_type_f:
        items = [r for r in items if r["event_type"] == event_type_f]
    # Stable order by (created_at, _seq) — same as scaffold §1.3 attempt_escalation rule
    items.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(items)
    page = paginate(items, limit, offset)
    return listing([audit_event_view(r) for r in page], total, limit, offset)
