"""AuditLog append helper with hash chaining per PRD §2.8."""

import hashlib
import json

from db import DB, new_id
from clock import now


def _canonical_json(obj) -> str:
    """Stable canonical JSON encoding for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def append_audit(*, contract_id=None, template_id=None, actor_user_id: str,
                 actor_role: str, action: str, payload: dict) -> dict:
    """Append a new AuditLog row, chaining per (contract_id || template_id)."""
    # Find prev_log_sha256 in chain
    prev = None
    if contract_id is not None:
        for row in reversed(DB.audit_logs):
            if row.get("contract_id") == contract_id:
                prev = row["payload_sha256"]
                break
    elif template_id is not None:
        for row in reversed(DB.audit_logs):
            if row.get("template_id") == template_id and row.get("contract_id") is None:
                prev = row["payload_sha256"]
                break

    payload_str = _canonical_json(payload)
    payload_sha = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

    occurred = now()
    row = {
        "id": new_id(),
        "contract_id": contract_id,
        "template_id": template_id,
        "actor_user_id": actor_user_id,
        "actor_role": actor_role,
        "action": action,
        "payload_sha256": payload_sha,
        "prev_log_sha256": prev,
        "occurred_at": occurred,
        "created_at": occurred,
    }
    DB.audit_logs.append(row)
    return row


def audit_chain_tip(contract_id: str = None) -> str:
    """Return the most recent payload_sha256 in the chain for a contract."""
    if contract_id is None:
        return None
    for row in reversed(DB.audit_logs):
        if row.get("contract_id") == contract_id:
            return row["payload_sha256"]
    return None
