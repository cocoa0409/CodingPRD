"""Audit and partner-sync event helpers."""
import db


def append_audit(actor_role: str, actor_id: str, action_type: str,
                 target_entity: str, target_id: str, payload: dict) -> dict:
    row = {
        "id": db.new_id(),
        "created_at": db.now_str(),
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action_type": action_type,
        "target_entity": target_entity,
        "target_id": target_id,
        "payload": payload,
    }
    db.audit_logs[row["id"]] = row
    return row


def emit_sync(channel: str, event_type: str, payload: dict) -> dict:
    row = {
        "id": db.new_id(),
        "created_at": db.now_str(),
        "channel": channel,
        "event_type": event_type,
        "payload": payload,
    }
    db.partner_sync_events[row["id"]] = row
    return row
