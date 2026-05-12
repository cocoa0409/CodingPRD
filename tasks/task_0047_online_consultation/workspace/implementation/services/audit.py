"""Audit log writer."""

from __future__ import annotations

import hashlib
import json

from flask import g

import db


def _digest(payload) -> str:
    """Stable hash of request body (tamper-evidence)."""
    try:
        canonical = json.dumps(payload or {}, sort_keys=True, default=str)
    except Exception:
        canonical = str(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def append_audit(action_code: str, target_entity: str, target_id: str, payload=None):
    """Append a new AuditLog row."""
    row = {
        "actor_role": getattr(g, "role", None),
        "actor_user_id": getattr(g, "user_id", None),
        "action_code": action_code,
        "target_entity": target_entity,
        "target_id": target_id,
        "occurred_at": db.now_iso(),
        "payload_digest": _digest(payload),
    }
    return db.insert("audit_logs", row, with_version=False)
