"""Append-only audit ledger writer (PRD §2.12)."""

import hashlib
import json
from typing import Any, Optional

from clock import clock
from db import _format_iso, new_id, store, utcnow_iso
from middleware import current_actor


def _hash_payload(payload: Any) -> str:
    if payload is None:
        payload = {}
    try:
        s = json.dumps(payload, sort_keys=True, default=str)
    except TypeError:
        s = str(payload)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def log_event(
    entity_type: str,
    entity_id: str,
    action: str,
    payload: Optional[Any] = None,
    actor_user_id: Optional[str] = None,
    actor_role: Optional[str] = None,
) -> None:
    """Append a single immutable audit record."""
    if actor_user_id is None or actor_role is None:
        a_user, a_role = current_actor()
        actor_user_id = actor_user_id or a_user or "system"
        actor_role = actor_role or a_role or "system"

    occurred = _format_iso(clock.now())
    event = {
        "id": new_id(),
        "created_at": utcnow_iso(),
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action": action,
        "payload_hash": _hash_payload(payload),
        "occurred_at": occurred,
    }
    store.audit_events.append(event)
