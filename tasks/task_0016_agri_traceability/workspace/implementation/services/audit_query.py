"""Audit log query service (RegulatoryOfficer only)."""

from common import paginate, parse_pagination, sort_by_created_at
from db import db


def _serialize(log: dict) -> dict:
    return {
        "id": log["id"],
        "created_at": log["created_at"],
        "actor_user_id": log["actor_user_id"],
        "actor_role": log["actor_role"],
        "entity_type": log["entity_type"],
        "entity_id": log["entity_id"],
        "action": log["action"],
        "before_state": log.get("before_state"),
        "after_state": log["after_state"],
        "change_summary": log.get("change_summary", {}),
    }


def list_audit_logs(args):
    limit, offset = parse_pagination()
    items = list(db.audit_logs)
    et = args.get("entity_type")
    eid = args.get("entity_id")
    action = args.get("action")
    if et is not None:
        items = [l for l in items if l["entity_type"] == et]
    if eid is not None:
        items = [l for l in items if l["entity_id"] == eid]
    if action is not None:
        items = [l for l in items if l["action"] == action]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return [_serialize(l) for l in page], limit, offset, total
