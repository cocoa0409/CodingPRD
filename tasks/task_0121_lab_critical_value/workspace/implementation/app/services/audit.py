"""ComplianceAuditEvent writer — append-only."""
from __future__ import annotations

from typing import Any

from ..clock import now
from ..helpers import new_uuid
from ..store import store


def write_audit_event(
    event_type: str,
    lab_order_id: str,
    actor_id: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    s = store()
    s.audit_sequence += 1
    row = {
        "id": new_uuid(),
        "created_at": now(),
        "event_type": event_type,
        "lab_order_id": lab_order_id,
        "actor_id": actor_id,
        "payload": payload or {},
        # Hidden ordering key — ensures stable ordering even when multiple
        # events are written in the same microsecond.
        "_seq": s.audit_sequence,
    }
    s.audit_events[row["id"]] = row
    return row
