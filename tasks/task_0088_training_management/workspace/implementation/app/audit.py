"""Audit logging service: ENROLLMENT and CREDIT_POOL subjects only (PRD §3.7)."""
from __future__ import annotations

from typing import Any, Optional

from .auth import current_actor
from .store import common_fields_append_only, get_store


def write_audit(
    subject_kind: str,
    subject_id: str,
    action: str,
    before: Optional[dict[str, Any]] = None,
    after: Optional[dict[str, Any]] = None,
) -> None:
    actor_id, actor_role = current_actor()
    store = get_store()
    base = common_fields_append_only()
    row = {
        **base,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action": action,
        "before": before or {},
        "after": after or {},
    }
    store.audit_logs[base["id"]] = row
