"""CaseEvent append helpers (scaffold §3.7, §1.1)."""
from __future__ import annotations

from typing import Dict, Any, Optional

import db


def append_event(
    case_id: str,
    event_type: str,
    payload_json: Optional[Dict[str, Any]] = None,
    from_status: Optional[str] = None,
    to_status: Optional[str] = None,
) -> Dict[str, Any]:
    """Append a CaseEvent. Returns the persisted row.

    CaseEvent is immutable — only id and created_at among system stamps. The
    PRD also exposes occurred_at on the event, stamped to the wall-clock now.
    """
    occurred_at = db.now_iso()
    event = {
        "case_id": case_id,
        "event_type": event_type,
        "from_status": from_status,
        "to_status": to_status,
        "payload_json": payload_json if payload_json is not None else {},
        "occurred_at": occurred_at,
    }
    db.stamp_immutable(event)
    db.case_events[event["id"]] = event
    return event
