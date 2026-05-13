"""Audit log append-only writer."""

from flask import g
from db import DB, new_id
from services.common import init_append_only
from services.time_util import format_iso


def append_audit(plan, action_code, target_entity, target_id, payload_summary=None):
    """Append an AuditLogEntry. occurred_ts is plan clock at the moment of transition."""
    eid = new_id()
    entry = {
        "id": eid,
        "plan_id": plan["id"] if plan else None,
        "actor_id": getattr(g, "user_id", None),
        "actor_role": getattr(g, "user_role", None),
        "action_code": action_code,
        "target_entity": target_entity,
        "target_id": target_id,
        "payload_summary": payload_summary or {},
        "occurred_ts": _plan_clock_iso(plan),
    }
    init_append_only(entry)
    DB["audit_log"][eid] = entry
    return entry


def _plan_clock_iso(plan):
    if plan and plan.get("current_clock_ts"):
        return format_iso(plan["current_clock_ts"]) if not isinstance(plan["current_clock_ts"], str) else plan["current_clock_ts"]
    return None
