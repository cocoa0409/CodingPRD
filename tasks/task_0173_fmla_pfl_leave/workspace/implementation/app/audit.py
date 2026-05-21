"""AuditEvent emission helpers."""
from __future__ import annotations

from typing import Any, Dict, Optional

from .clock import format_datetime_ms, get_clock
from .store import get_store, new_id


VALID_EVENT_KINDS = {
    "ELIGIBILITY_CHECKED",
    "CASE_CREATED",
    "CERTIFICATION_SUBMITTED",
    "CERTIFICATION_REVIEWED",
    "INSTANCE_LOGGED",
    "INSTANCE_VOIDED",
    "QUOTA_RECOMPUTED",
    "PFL_LINKED",
    "JOB_RESTORATION_REQUESTED",
    "JOB_RESTORATION_FORFEITED",
    "BENEFIT_INVOICE_ISSUED",
    "BENEFIT_INVOICE_FORFEITED",
}


def emit_audit(
    leave_case_id: str,
    event_kind: str,
    actor_role: str,
    detail_json: Optional[Dict[str, Any]] = None,
) -> dict:
    if event_kind not in VALID_EVENT_KINDS:
        raise ValueError(f"Unknown event_kind: {event_kind}")
    store = get_store()
    now_iso = format_datetime_ms(get_clock().get())
    event_id = new_id()
    row = {
        "id": event_id,
        "leave_case_id": leave_case_id,
        "event_kind": event_kind,
        "actor_role": actor_role,
        "detail_json": detail_json or {},
        "created_at": now_iso,
        "_seq": store.next_seq(),
    }
    store.audit_events[event_id] = row
    return row
