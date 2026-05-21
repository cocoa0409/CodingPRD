"""Audit-log routes — PayrollAdmin only."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..auth import require_roles
from ..pagination import paginate, parse_pagination
from ..response import make_array_envelope
from ..serializers import audit_view
from ..store import get_store


bp_audit = Blueprint("audit", __name__)


@bp_audit.route("/timekeeping/audit", methods=["GET"])
@require_roles("PayrollAdmin")
def list_audit_route(actor_user_id: str, actor_role: str):
    limit, offset = parse_pagination()
    subject_entity = request.args.get("subject_entity")
    subject_id = request.args.get("subject_id")
    action = request.args.get("action")

    store = get_store()
    rows = list(store.audit_entries.values())
    rows.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    if subject_entity is not None:
        rows = [r for r in rows if r.get("subject_entity") == subject_entity]
    if subject_id is not None:
        rows = [r for r in rows if r.get("subject_id") == subject_id]
    if action is not None:
        rows = [r for r in rows if r.get("action") == action]
    total = len(rows)
    page = paginate(rows, limit, offset)
    views = [audit_view(r) for r in page]
    return (
        jsonify(make_array_envelope(views, limit=limit, offset=offset, total_count=total)),
        200,
    )
