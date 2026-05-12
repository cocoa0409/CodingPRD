"""Audit log listing."""
from flask import Blueprint, request

import db
from middleware import require_auth, get_pagination
from response import success_list


bp = Blueprint("audit_logs", __name__)


def _public(a: dict) -> dict:
    return {
        "id": a["id"],
        "actor_role": a["actor_role"],
        "actor_id": a.get("actor_id"),
        "event_type": a["event_type"],
        "target_entity": a["target_entity"],
        "target_id": a["target_id"],
        "detail": a.get("detail", {}),
        "created_at": a["created_at"],
    }


@bp.route("/audit-logs", methods=["GET"])
@require_auth(roles={"PlatformAdmin"})
def list_audit_logs():
    limit, offset = get_pagination()
    event_type = request.args.get("event_type")
    target_entity = request.args.get("target_entity")
    target_id = request.args.get("target_id")

    rows = list(db.audit_logs.values())
    if event_type is not None:
        rows = [r for r in rows if r["event_type"] == event_type]
    if target_entity is not None:
        rows = [r for r in rows if r["target_entity"] == target_entity]
    if target_id is not None:
        rows = [r for r in rows if r["target_id"] == target_id]

    rows.sort(key=lambda r: r["_seq"])  # created_at ascending
    total = len(rows)
    page = rows[offset: offset + limit]
    return success_list([_public(r) for r in page], limit, offset, total)
