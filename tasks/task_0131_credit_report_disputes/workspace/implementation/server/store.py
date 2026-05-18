"""In-memory data store + UUID / timestamp helpers."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    """ISO 8601 UTC with millisecond precision and trailing 'Z'."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class Store:
    """Thread-safe in-memory document collections, keyed by id."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.consumers: dict[str, dict[str, Any]] = {}
        self.furnishers: dict[str, dict[str, Any]] = {}
        self.credit_reports: dict[str, dict[str, Any]] = {}
        self.tradeline_items: dict[str, dict[str, Any]] = {}
        self.disputes: dict[str, dict[str, Any]] = {}
        self.furnisher_inquiries: dict[str, dict[str, Any]] = {}
        self.result_notices: dict[str, dict[str, Any]] = {}
        self.regulatory_complaints: dict[str, dict[str, Any]] = {}
        self.credit_freezes: dict[str, dict[str, Any]] = {}
        self.credit_locks: dict[str, dict[str, Any]] = {}
        self.hard_inquiries: dict[str, dict[str, Any]] = {}
        # Auxiliary index: dispute -> list of regulatory complaint statuses through history
        self.dispute_escalation_history: dict[str, bool] = {}


store = Store()


def stamp_create(entity: dict[str, Any]) -> dict[str, Any]:
    """Populate id, created_at, updated_at, version on a fresh resource."""
    ts = now_iso()
    entity.setdefault("id", new_id())
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def stamp_create_append_only(entity: dict[str, Any]) -> dict[str, Any]:
    """Append-only audit rows carry only id + created_at."""
    entity.setdefault("id", new_id())
    entity["created_at"] = now_iso()
    return entity


def stamp_update(entity: dict[str, Any]) -> dict[str, Any]:
    """Bump updated_at and version on every mutation, including server-driven ones."""
    entity["updated_at"] = now_iso()
    entity["version"] = int(entity.get("version", 0)) + 1
    return entity
