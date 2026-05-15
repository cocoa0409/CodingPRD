"""In-memory data store with UUID/timestamp helpers and a global lock.

All entity collections live here. A single re-entrant lock guards mutations
to keep multi-entity cascades atomic relative to other requests.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime
from typing import Any, Dict

from .clock import clock


def new_id() -> str:
    return str(uuid.uuid4())


def fmt_ts(dt: datetime) -> str:
    """ISO 8601 UTC, millisecond precision, Z suffix."""
    ms = f"{dt.microsecond // 1000:03d}"
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ms + "Z"


def now_ts() -> str:
    return fmt_ts(clock.now())


class Store:
    """Top-level in-memory store with one dict per entity kind."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.authors: Dict[str, dict] = {}
        self.reviewers: Dict[str, dict] = {}
        self.editors: Dict[str, dict] = {}
        self.manuscripts: Dict[str, dict] = {}
        self.coauthor_confirmations: Dict[str, dict] = {}
        self.plagiarism_checks: Dict[str, dict] = {}
        self.reviewer_invitations: Dict[str, dict] = {}
        self.reviews: Dict[str, dict] = {}
        self.editor_decisions: Dict[str, dict] = {}
        self.publications: Dict[str, dict] = {}
        self.audit_logs: list[dict] = []

    # ----- helpers for the common envelope fields -----

    def stamp_create(self, payload: dict) -> dict:
        ts = now_ts()
        payload.setdefault("id", new_id())
        payload["created_at"] = ts
        payload["updated_at"] = ts
        payload["version"] = 1
        return payload

    def stamp_update(self, payload: dict) -> dict:
        payload["updated_at"] = now_ts()
        payload["version"] = payload.get("version", 0) + 1
        return payload

    def stamp_event(self, payload: dict) -> dict:
        """For write-once event records (PlagiarismCheck, AuditLog).

        These carry only `id` and `created_at`."""
        payload.setdefault("id", new_id())
        payload["created_at"] = now_ts()
        return payload

    # ----- audit log -----

    def append_audit(
        self,
        actor_role: str,
        actor_id: str,
        entity: str,
        entity_id: str,
        action: str,
        from_state: str | None = None,
        to_state: str | None = None,
        details: dict | None = None,
    ) -> dict:
        row = {
            "actor_role": actor_role,
            "actor_id": actor_id,
            "entity": entity,
            "entity_id": entity_id,
            "action": action,
            "from_state": from_state,
            "to_state": to_state,
            "details": details or {},
        }
        self.stamp_event(row)
        self.audit_logs.append(row)
        return row


# Singleton store
store = Store()
