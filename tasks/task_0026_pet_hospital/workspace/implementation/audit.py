"""Audit log — append-only entries (PRD §3.10)."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional

import db
from clock import now_iso


def write_audit(*, subject_type: str, subject_id: str, actor_role: str,
                actor_id: str, action: str, from_state: Optional[str],
                to_state: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = payload or {}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    ts = now_iso()
    log = {
        "id": db.new_uuid(),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action": action,
        "from_state": from_state,
        "to_state": to_state,
        "payload_hash": payload_hash,
        "occurred_at": ts,
        "created_at": ts,
    }
    db.audit_logs.append(log)
    return log
