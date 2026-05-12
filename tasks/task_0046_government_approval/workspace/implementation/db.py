"""In-memory data store with logical clock and helpers."""

from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone


# --- Logical clock --------------------------------------------------------
# Tests can advance the clock through POST /_clock/advance.
_clock_offset = timedelta(0)


def _real_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def now_dt() -> datetime:
    """Current logical UTC datetime."""
    return _real_utc_now() + _clock_offset


def format_ts(dt: datetime) -> str:
    """ISO 8601 UTC timestamp with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso() -> str:
    return format_ts(now_dt())


def parse_iso(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def advance_clock(seconds: int) -> None:
    """Advance the logical clock by N seconds."""
    global _clock_offset
    _clock_offset += timedelta(seconds=seconds)


def reset_clock():
    global _clock_offset
    _clock_offset = timedelta(0)


# --- ID generation --------------------------------------------------------
_ALPHA = string.ascii_letters + string.digits


def new_id() -> str:
    """Server-allocated UUID expressed without prefix."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    body = "".join(secrets.choice(_ALPHA) for _ in range(20))
    return f"req_{body}"


# --- Tables ---------------------------------------------------------------
TABLES = [
    "departments",
    "matters",
    "matter_versions",
    "material_templates",
    "certificate_templates",
    "applications",
    "review_tasks",
    "correction_notices",
    "certificates",
    "external_events",
    "audit_logs",
]

_tables: dict[str, list[dict]] = {name: [] for name in TABLES}

# Per-day per-matter sequence counter for certificate serial numbers.
_cert_seq: dict[str, int] = {}

# Global insertion sequence — tie-breaker for created_at ties.
_SEQ_COUNTER = {"value": 0}


def _next_seq() -> int:
    _SEQ_COUNTER["value"] += 1
    return _SEQ_COUNTER["value"]


# Entities that carry updated_at + version (per scaffold §2.4).
_FAT_TABLES = {
    "departments",
    "matters",
    "matter_versions",
    "material_templates",
    "certificate_templates",
    "applications",
    "review_tasks",
    "certificates",
}


def reset_all():
    """Wipe in-memory state (test hook)."""
    global _clock_offset
    _clock_offset = timedelta(0)
    for name in TABLES:
        _tables[name].clear()
    _cert_seq.clear()
    _SEQ_COUNTER["value"] = 0


def insert(table: str, data: dict) -> dict:
    """Insert a record, auto-populating id / created_at and (for fat tables) updated_at + version."""
    record = dict(data)
    record["id"] = record.get("id") or new_id()
    record["created_at"] = record.get("created_at") or now_iso()
    record["_seq"] = _next_seq()
    if table in _FAT_TABLES:
        record.setdefault("updated_at", record["created_at"])
        record.setdefault("version", 1)
    _tables[table].append(record)
    return record


def update(table: str, record_id: str, updates: dict, bump: bool = True) -> dict | None:
    for row in _tables[table]:
        if row["id"] == record_id:
            row.update(updates)
            if bump and table in _FAT_TABLES:
                row["updated_at"] = now_iso()
                row["version"] = row.get("version", 0) + 1
            return row
    return None


def touch(table: str, record_id: str) -> dict | None:
    """Bump updated_at + version on a fat-table row without mutating other fields."""
    for row in _tables[table]:
        if row["id"] == record_id:
            if table in _FAT_TABLES:
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
    return [row for row in _tables[table]
            if all(row.get(k) == v for k, v in filters.items())]


def all_rows(table: str) -> list[dict]:
    return list(_tables[table])


def query(table, filters=None, sort_key="created_at", sort_reverse=False,
          limit=10, offset=0):
    """Paginated query — returns (page, total_count) sorted by sort_key ASC."""
    rows = _tables[table]
    if filters:
        rows = [r for r in rows
                if all(r.get(k) == v for k, v in filters.items() if v is not None)]
    rows = sorted(
        rows,
        key=lambda r: (r.get(sort_key) or "", r.get("_seq") or 0),
        reverse=sort_reverse,
    )
    total = len(rows)
    return rows[offset:offset + limit], total


def next_cert_seq(matter_code: str, day_str: str) -> int:
    """Per-day per-matter sequence counter for certificate serial numbers."""
    key = f"{matter_code}:{day_str}"
    _cert_seq[key] = _cert_seq.get(key, 0) + 1
    return _cert_seq[key]
