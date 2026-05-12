"""In-memory data store with UUID/timestamp helpers."""

from __future__ import annotations

import secrets
import string
import uuid
from datetime import datetime, timezone


def _real_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def format_ts(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso() -> str:
    return format_ts(_real_utc_now())


_ALPHA = string.ascii_letters + string.digits


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    body = "".join(secrets.choice(_ALPHA) for _ in range(20))
    return f"req_{body}"


# --- Tables ---------------------------------------------------------------
TABLES = [
    "projects",
    "modules",
    "team_members",
    "defects",
    "defect_attachments",
    "duplicate_links",
    "severity_overrides",
    "fix_records",
    "verification_records",
    "regression_runs",
    "sla_pauses",
    "audit_entries",
]

_tables: dict[str, list[dict]] = {name: [] for name in TABLES}

_SEQ_COUNTER = {"value": 0}


def _next_seq() -> int:
    _SEQ_COUNTER["value"] += 1
    return _SEQ_COUNTER["value"]


# Entities with updated_at + version
_FAT_TABLES = {
    "projects", "modules", "team_members", "defects",
    "severity_overrides", "regression_runs",
}


def reset_all():
    for name in TABLES:
        _tables[name].clear()
    _SEQ_COUNTER["value"] = 0


def insert(table: str, data: dict) -> dict:
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
          limit=10, offset=0, predicate=None):
    rows = _tables[table]
    if filters:
        rows = [r for r in rows
                if all(r.get(k) == v for k, v in filters.items() if v is not None)]
    if predicate:
        rows = [r for r in rows if predicate(r)]
    rows = sorted(
        rows,
        key=lambda r: (r.get(sort_key) or "", r.get("_seq") or 0),
        reverse=sort_reverse,
    )
    total = len(rows)
    return rows[offset:offset + limit], total
