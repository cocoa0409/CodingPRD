"""AuditLog list endpoint (PRD §2.9)."""
from __future__ import annotations

from flask import Blueprint, request

from db import audit_logs
from errors import ERR_VALIDATION, raise_err
from middleware import require_role
from response import success_list
from services.validators import parse_pagination


bp = Blueprint("audit_logs", __name__)


EVENT_KINDS = {"BILLING_ADJUSTMENT", "OPS_ACTION", "EXTERNAL_SYNC"}


def _serialize(a: dict) -> dict:
    return dict(a)


@bp.get("/audit-logs")
def list_audit_logs():
    require_role("Admin")
    event_kind = request.args.get("event_kind")
    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    actor_role = request.args.get("actor_role")

    if event_kind is not None and event_kind not in EVENT_KINDS:
        raise_err(ERR_VALIDATION, "event_kind filter invalid")

    items = list(audit_logs.values())
    if event_kind is not None:
        items = [a for a in items if a.get("event_kind") == event_kind]
    if subject_type is not None:
        items = [a for a in items if a.get("subject_type") == subject_type]
    if subject_id is not None:
        items = [a for a in items if a.get("subject_id") == subject_id]
    if actor_role is not None:
        items = [a for a in items if a.get("actor_role") == actor_role]

    items.sort(key=lambda a: a["created_at"])
    limit, offset = parse_pagination()
    total = len(items)
    window = items[offset:offset + limit]
    return success_list([_serialize(a) for a in window], limit=limit, offset=offset, total_count=total)
