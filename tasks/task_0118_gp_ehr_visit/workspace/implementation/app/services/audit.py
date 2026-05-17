"""Audit log writer."""
from __future__ import annotations

from typing import Optional

from ..clock import now
from ..helpers import new_uuid
from ..store import store


def write_audit(
    *,
    actor_role: str,
    actor_id: str,
    action: str,
    target_entity: str,
    target_id: str,
    epcs_signature_hash: Optional[str] = None,
) -> dict:
    s = store()
    row = {
        "id": new_uuid(),
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action": action,
        "target_entity": target_entity,
        "target_id": target_id,
        "epcs_signature_hash": epcs_signature_hash,
        "occurred_at": now(),
    }
    s.audit_logs[row["id"]] = row
    return row
