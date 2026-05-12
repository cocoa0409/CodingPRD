"""Append-only audit log writer."""

from __future__ import annotations

from flask import g

import db


def write(action: str, target_entity: str, target_id: str,
          payload_snapshot: dict | None = None) -> dict:
    return db.insert("audit_logs", {
        "actor_role": getattr(g, "role", None),
        "actor_id": getattr(g, "user_id", None),
        "action": action,
        "target_entity": target_entity,
        "target_id": target_id,
        "payload_snapshot": payload_snapshot or {},
    })
