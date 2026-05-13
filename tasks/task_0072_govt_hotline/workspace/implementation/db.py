"""In-memory database with UUID generation, timestamp management, and a global RLock.

Tables map name -> list[dict]. Resources are dictionaries with `id`, `created_at`,
and for most entities `updated_at` and `version`. ClarificationPause, AuditLog,
and SyncEvent are log-style: they expose only `id` and `created_at`.
"""

import uuid
import threading
from typing import Optional

import clock

# Re-entrant lock — the same request thread may take it multiple times across
# nested service calls (e.g., resolve cascades into survey auto-dispatch, audit
# writes, and sync emission, all of which hit the store).
LOCK = threading.RLock()

# Log-only tables: no updated_at, no version on their rows.
_LOG_TABLES = {"clarification_pauses", "audit_logs", "sync_events"}

_tables: dict[str, list[dict]] = {
    "departments": [],
    "handlers": [],
    "category_rules": [],
    "work_orders": [],
    "department_assignments": [],
    "clarification_pauses": [],
    "satisfaction_surveys": [],
    "supervision_tasks": [],
    "audit_logs": [],
    "sync_events": [],
}


def new_id() -> str:
    return str(uuid.uuid4())


def request_id() -> str:
    return "req_" + uuid.uuid4().hex[:20].upper()


def insert(table: str, data: dict) -> dict:
    """Insert a record. Fills in id/created_at (and updated_at/version for non-log tables) if not provided."""
    record = dict(data)
    record.setdefault("id", new_id())
    record.setdefault("created_at", clock.now_iso())
    if table not in _LOG_TABLES:
        record.setdefault("updated_at", record["created_at"])
        record.setdefault("version", 1)
    _tables[table].append(record)
    return record


def all_rows(table: str) -> list[dict]:
    return _tables[table]


def find_by_id(table: str, rid: Optional[str]) -> Optional[dict]:
    if rid is None:
        return None
    for row in _tables[table]:
        if row["id"] == rid:
            return row
    return None


def find_one(table: str, **filters) -> Optional[dict]:
    for row in _tables[table]:
        if all(row.get(k) == v for k, v in filters.items()):
            return row
    return None


def find_many(table: str, **filters) -> list[dict]:
    return [r for r in _tables[table] if all(r.get(k) == v for k, v in filters.items())]


def update_fields(record: dict, updates: dict, log: bool = False) -> dict:
    """Apply updates to `record` in place. Bumps version+updated_at unless log=True."""
    for k, v in updates.items():
        record[k] = v
    if not log:
        record["updated_at"] = clock.now_iso()
        record["version"] = int(record.get("version", 0)) + 1
    return record


def bump(record: dict) -> dict:
    """Bump updated_at and version without other field changes."""
    record["updated_at"] = clock.now_iso()
    record["version"] = int(record.get("version", 0)) + 1
    return record


def count(table: str, **filters) -> int:
    return len(find_many(table, **filters))


def reset():
    """Test-only: clear all tables (not used by the API)."""
    for k in _tables:
        _tables[k] = []
