"""Audit log + downstream sync event emitters."""

from flask import g

import clock
import db


def write_audit(action: str, work_order_id: str = None, payload: dict = None) -> dict:
    row = {
        "id": db.new_id(),
        "work_order_id": work_order_id,
        "action": action,
        "actor_role": getattr(g, "role", None),
        "actor_id": getattr(g, "user_id", None),
        "payload": payload or {},
        "occurred_at": clock.now_iso(),
        "created_at": clock.now_iso(),
    }
    db.all_rows("audit_logs").append(row)
    return row


SYNC_PLATFORMS = ("IM", "GOVT_AFFAIRS", "INTER_DEPT")


def emit_sync(work_order_id: str, event_type: str, payload: dict = None) -> list[dict]:
    """Emit one SyncEvent row per target platform."""
    out = []
    ts = clock.now_iso()
    for platform in SYNC_PLATFORMS:
        row = {
            "id": db.new_id(),
            "work_order_id": work_order_id,
            "event_type": event_type,
            "target_platform": platform,
            "payload": dict(payload or {}),
            "delivery_status": "PENDING",
            "emitted_at": ts,
            "created_at": ts,
        }
        db.all_rows("sync_events").append(row)
        out.append(row)
    return out


def latest_activity_timestamp(work_order_id: str) -> str:
    """Latest occurred_at among AuditLogs for this WO with action in {ACCEPT, OPINION_SUBMIT, RESOLVE}."""
    relevant = [
        r for r in db.all_rows("audit_logs")
        if r.get("work_order_id") == work_order_id
        and r.get("action") in ("ACCEPT", "OPINION_SUBMIT", "RESOLVE")
    ]
    if not relevant:
        return None
    return max(r["occurred_at"] for r in relevant)
