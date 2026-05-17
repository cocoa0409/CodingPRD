"""Audit log read endpoint."""
from __future__ import annotations

from flask import Blueprint, request

from ..auth import ROLE_CLINIC_ADMIN, require_roles
from ..helpers import paginate, parse_pagination
from ..responses import listing
from ..services.serialize import audit_to_dict
from ..store import store

bp = Blueprint("audit_routes", __name__)


@bp.route("/audit-logs", methods=["GET"])
@require_roles(ROLE_CLINIC_ADMIN)
def list_audit(**_kwargs):
    limit, offset = parse_pagination()
    target_entity = request.args.get("target_entity")
    target_id = request.args.get("target_id")
    actor_id = request.args.get("actor_id")
    action = request.args.get("action")
    s = store()
    with s.lock:
        items = list(s.audit_logs.values())
        if target_entity is not None:
            items = [r for r in items if r.get("target_entity") == target_entity]
        if target_id is not None:
            items = [r for r in items if r.get("target_id") == target_id]
        if actor_id is not None:
            items = [r for r in items if r.get("actor_id") == actor_id]
        if action is not None:
            items = [r for r in items if r.get("action") == action]
        items.sort(key=lambda r: r["occurred_at"])
        total = len(items)
        page = paginate(items, limit, offset)
        out = [audit_to_dict(r) for r in page]
    return listing(out, total, limit, offset)
