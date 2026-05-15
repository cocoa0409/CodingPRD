"""In-memory data store for the recruitment platform.

Each resource is kept in a dict keyed by its server-minted UUID v4 string.
Helper functions handle id generation, common-field updates, and the
audit-event log.
"""
from __future__ import annotations

import threading
import uuid
from typing import Any, Dict, List, Optional

from clock import iso_now


_LOCK = threading.RLock()


def new_id() -> str:
    return str(uuid.uuid4())


class _Store:
    def __init__(self) -> None:
        self.companies: Dict[str, Dict[str, Any]] = {}
        self.hr_users: Dict[str, Dict[str, Any]] = {}
        self.job_postings: Dict[str, Dict[str, Any]] = {}
        self.candidates: Dict[str, Dict[str, Any]] = {}
        self.applications: Dict[str, Dict[str, Any]] = {}
        self.interview_rounds: Dict[str, Dict[str, Any]] = {}
        self.offers: Dict[str, Dict[str, Any]] = {}
        self.onboardings: Dict[str, Dict[str, Any]] = {}
        self.headhunter_contracts: Dict[str, Dict[str, Any]] = {}
        self.commission_records: Dict[str, Dict[str, Any]] = {}
        self.audit_events: List[Dict[str, Any]] = []
        # Track processed external events for idempotency.
        self.processed_external_events: set = set()


store = _Store()


def lock():
    return _LOCK


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------
def init_common_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    ts = iso_now()
    row.setdefault("id", new_id())
    row.setdefault("created_at", ts)
    row["updated_at"] = ts
    row["version"] = 1
    return row


def init_no_common_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    """For CommissionRecord and AuditEvent — id and created_at only."""
    row.setdefault("id", new_id())
    row.setdefault("created_at", iso_now())
    return row


def bump(row: Dict[str, Any]) -> Dict[str, Any]:
    row["updated_at"] = iso_now()
    row["version"] = int(row.get("version", 1)) + 1
    return row


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------
def append_audit(
    *,
    subject_entity: str,
    subject_id: str,
    event_kind: str,
    from_state: Optional[str],
    to_state: Optional[str],
    actor_role: str,
    actor_user_id: str,
) -> Dict[str, Any]:
    row = {
        "id": new_id(),
        "created_at": iso_now(),
        "subject_entity": subject_entity,
        "subject_id": subject_id,
        "event_kind": event_kind,
        "from_state": from_state,
        "to_state": to_state,
        "actor_role": actor_role,
        "actor_user_id": actor_user_id,
    }
    store.audit_events.append(row)
    return row
