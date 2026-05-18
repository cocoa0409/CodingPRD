"""AuditLog read-only endpoint (PRD §2.11)."""
from __future__ import annotations

from flask import Blueprint, request

from config import ROLE_IRSADJUDICATOR
from db import store
from middleware import require_auth
from response import list_success

from routes._helpers import parse_pagination


bp = Blueprint("audit_logs", __name__)


def _serialize_entry(e: dict) -> dict:
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "actor_role": e["actor_role"],
        "actor_id": e["actor_id"],
        "action": e["action"],
        "target_entity": e["target_entity"],
        "target_id": e["target_id"],
        "payload": e["payload"],
    }


@bp.get("/audit-logs")
@require_auth([ROLE_IRSADJUDICATOR])
def list_audit_logs():
    limit, offset = parse_pagination()
    f_role = request.args.get("actor_role")
    f_action = request.args.get("action")
    f_target_entity = request.args.get("target_entity")
    f_target_id = request.args.get("target_id")

    rows = list(store.audit_logs)
    if f_role is not None:
        rows = [r for r in rows if r["actor_role"] == f_role]
    if f_action is not None:
        rows = [r for r in rows if r["action"] == f_action]
    if f_target_entity is not None:
        rows = [r for r in rows if r["target_entity"] == f_target_entity]
    if f_target_id is not None:
        rows = [r for r in rows if r["target_id"] == f_target_id]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_success([_serialize_entry(r) for r in page], limit, offset, total, 200)
