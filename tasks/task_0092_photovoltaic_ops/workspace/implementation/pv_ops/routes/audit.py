"""Audit log query endpoint."""
from __future__ import annotations

from flask import Blueprint, current_app, request

from pv_ops.auth import require_roles
from pv_ops.responses import listed
from pv_ops.services import serializers
from pv_ops.store import paginate
from pv_ops.utils import parse_pagination


bp = Blueprint("audit", __name__)


@bp.route("/pv-ops/audit-entries", methods=["GET"])
@require_roles("PlatformAdmin", "FinanceOfficer")
def list_audits():
    store = current_app.extensions["store"]
    limit, offset = parse_pagination(request.args)
    target_type = request.args.get("target_type")
    target_id = request.args.get("target_id")
    actor_id = request.args.get("actor_id")
    with store.lock:
        rows = list(store.audit_entries.values())
        if target_type:
            rows = [r for r in rows if r.get("target_type") == target_type]
        if target_id:
            rows = [r for r in rows if r.get("target_id") == target_id]
        if actor_id:
            rows = [r for r in rows if r.get("actor_id") == actor_id]
        rows.sort(key=lambda r: r["created_at"])
        page, total, has_more = paginate(rows, limit, offset)
        return listed(
            [serializers.audit_view(r) for r in page],
            limit=limit,
            offset=offset,
            total_count=total,
            has_more=has_more,
        )
