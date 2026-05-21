"""Audit-trail helpers — append-only AuditEntry records."""
from __future__ import annotations

from typing import Any, Dict, Optional

from .clock import format_iso_ms
from .response import _now_iso_ms  # noqa: F401 — kept for symmetry
from .store import Store, new_id


def append_audit(
    store: Store,
    *,
    actor_user_id: str,
    actor_role: str,
    action: str,
    subject_entity: str,
    subject_id: str,
    before_snapshot: Optional[Dict[str, Any]] = None,
    after_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Insert an AuditEntry row. AuditEntry is append-only — no version/updated_at."""
    from .clock import get_clock
    now = format_iso_ms(get_clock().now())
    eid = new_id()
    row = {
        "id": eid,
        "created_at": now,
        "_seq": store.next_seq(),
        "actor_user_id": actor_user_id,
        "actor_role": actor_role,
        "action": action,
        "subject_entity": subject_entity,
        "subject_id": subject_id,
        "before_snapshot": before_snapshot or {},
        "after_snapshot": after_snapshot or {},
    }
    store.audit_entries[eid] = row
    return row
