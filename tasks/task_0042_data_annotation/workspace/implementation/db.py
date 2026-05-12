"""In-memory data store with logical clock and helpers."""

from __future__ import annotations

import uuid
import secrets
import string
from datetime import datetime, timezone, timedelta


# --- Logical clock --------------------------------------------------------
# Tests can advance the clock through POST /_clock/advance. All `now()` calls
# in mutating code paths read this clock so the system has a single source of
# truth for "current time".
_clock_offset = timedelta(0)


def _real_utc_now():
    return datetime.now(timezone.utc)


def now_dt() -> datetime:
    """Current logical UTC datetime."""
    return _real_utc_now() + _clock_offset


def format_ts(dt: datetime) -> str:
    """ISO 8601 UTC string with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso() -> str:
    return format_ts(now_dt())


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 datetime; supports trailing 'Z'."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def set_clock_to(target: datetime):
    """Set logical clock to exactly `target`."""
    global _clock_offset
    _clock_offset = target - _real_utc_now()


def reset_clock():
    global _clock_offset
    _clock_offset = timedelta(0)


def reset_all():
    """Wipe in-memory state — test-only hook, equivalent to a fresh server."""
    global _clock_offset
    _clock_offset = timedelta(0)
    for name in TABLES:
        _tables[name].clear()
    _SEQ_COUNTER["value"] = 0


# --- ID generation --------------------------------------------------------
_ALPHA = string.ascii_letters + string.digits


def new_id() -> str:
    """Server-allocated UUID expressed without prefix."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    """Random alphanumeric request id with the `req_` prefix per PRD §2.2."""
    body = ''.join(secrets.choice(_ALPHA) for _ in range(20))
    return f"req_{body}"


# --- Tables ---------------------------------------------------------------
TABLES = [
    "projects",
    "golden_samples",
    "task_packages",
    "annotators",
    "submissions",
    "inspections",
    "appeals",
    "ledger_entries",
    "payroll_periods",
    "audit_logs",
    "external_events",
]

_tables: dict[str, list[dict]] = {name: [] for name in TABLES}

# Global insertion sequence — tie-breaks records that share a millisecond
# timestamp during list/sort operations.
_SEQ_COUNTER = {"value": 0}


def _next_seq() -> int:
    _SEQ_COUNTER["value"] += 1
    return _SEQ_COUNTER["value"]


# Entities that have updated_at + version.
_FAT_TABLES = {
    "projects",
    "task_packages",
    "annotators",
    "inspections",
    "appeals",
    "payroll_periods",
}


def insert(table: str, data: dict, with_version: bool | None = None) -> dict:
    """Insert record, auto-populating id/created_at and (for fat tables) updated_at/version."""
    record = dict(data)
    record["id"] = record.get("id") or new_id()
    record["created_at"] = record.get("created_at") or now_iso()
    record["_seq"] = _next_seq()
    fat = with_version if with_version is not None else (table in _FAT_TABLES)
    if fat:
        record.setdefault("updated_at", record["created_at"])
        record.setdefault("version", 1)
    _tables[table].append(record)
    return record


def update(table: str, record_id: str, updates: dict, bump: bool = True) -> dict | None:
    """Update record; bumps updated_at/version when applicable."""
    for row in _tables[table]:
        if row["id"] == record_id:
            row.update(updates)
            if bump and table in _FAT_TABLES:
                row["updated_at"] = now_iso()
                row["version"] = row.get("version", 0) + 1
            return row
    return None


def find_by_id(table: str, record_id: str) -> dict | None:
    for row in _tables[table]:
        if row["id"] == record_id:
            return row
    return None


def find_one(table: str, **filters) -> dict | None:
    for row in _tables[table]:
        if all(row.get(k) == v for k, v in filters.items()):
            return row
    return None


def find_many(table: str, **filters) -> list[dict]:
    return [
        row for row in _tables[table]
        if all(row.get(k) == v for k, v in filters.items())
    ]


def all_rows(table: str) -> list[dict]:
    return list(_tables[table])


def query(
    table: str,
    filters: dict | None = None,
    sort_key: str = "created_at",
    sort_reverse: bool = False,
    limit: int = 10,
    offset: int = 0,
):
    """Return (page, total_count) sorted ascending by sort_key (default created_at)."""
    rows = _tables[table]
    if filters:
        rows = [
            r for r in rows
            if all(r.get(k) == v for k, v in filters.items() if v is not None)
        ]
    rows = sorted(
        rows,
        key=lambda r: (r.get(sort_key) or "", r.get("_seq") or 0),
        reverse=sort_reverse,
    )
    total = len(rows)
    return rows[offset:offset + limit], total
