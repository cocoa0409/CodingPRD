"""In-memory database with simple table dicts and a logical clock."""

import threading
import uuid
from datetime import datetime, timezone, timedelta

# Single global lock — small in-memory store, simple correctness.
LOCK = threading.RLock()

# Logical clock — singleton row id='clock', mutable only via /_clock/advance.
# Initialised to current wall-clock UTC at process start.
_clock_now = datetime.now(timezone.utc)

# Tables — each entity gets its own list.
_tables = {
    "letters_of_credit": [],
    "applicants": [],
    "beneficiaries": [],
    "banks": [],
    "lc_amendments": [],
    "swift_messages": [],
    "presentations": [],
    "documents": [],
    "examination_reports": [],
    "discrepancies": [],
    "payment_settlements": [],
    "reimbursement_claims": [],
    "expiry_alerts": [],
    "external_events": [],
    "audit_log_entries": [],
}

# Per-LC sequence counters
_lc_amendment_seq = {}
_lc_presentation_seq = {}
_lc_number_seq = 0  # for LC-YYYY-NNNNNN


def fmt_dt(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits, suffix 'Z'."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    """Parse ISO 8601 to aware UTC datetime. Returns None if s is None."""
    if s is None:
        return None
    if isinstance(s, datetime):
        if s.tzinfo is None:
            return s.replace(tzinfo=timezone.utc)
        return s.astimezone(timezone.utc)
    if not isinstance(s, str):
        return None
    s2 = s.strip()
    # Accept trailing 'Z' or +00:00
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s2)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now() -> datetime:
    """Current logical clock instant (aware UTC)."""
    return _clock_now


def now_iso() -> str:
    return fmt_dt(_clock_now)


def advance_clock(seconds: int):
    """Advance clock by seconds. Returns new datetime."""
    global _clock_now
    _clock_now = _clock_now + timedelta(seconds=int(seconds))
    return _clock_now


def set_clock(dt):
    global _clock_now
    _clock_now = dt


def get_clock_record():
    return {
        "id": "clock",
        "now": fmt_dt(_clock_now),
        "created_at": fmt_dt(_clock_now),
    }


def gen_id() -> str:
    return str(uuid.uuid4())


def insert(table: str, data: dict, with_version: bool = True) -> dict:
    """Insert into a table. Sets id, created_at, updated_at, version when with_version is True."""
    record = dict(data)
    record.setdefault("id", gen_id())
    record["created_at"] = now_iso()
    if with_version:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    _tables[table].append(record)
    return record


def update(table: str, record_id: str, updates: dict, bump: bool = True) -> dict:
    """Update record by id. If bump=True, refresh updated_at and increment version."""
    for row in _tables[table]:
        if row["id"] == record_id:
            row.update(updates)
            if bump and "version" in row:
                row["updated_at"] = now_iso()
                row["version"] = row.get("version", 0) + 1
            return row
    return None


def find_one(table: str, **filters):
    for row in _tables[table]:
        if all(row.get(k) == v for k, v in filters.items()):
            return row
    return None


def get_by_id(table: str, record_id: str):
    if record_id is None:
        return None
    for row in _tables[table]:
        if row["id"] == record_id:
            return row
    return None


def find_many(table: str, **filters):
    results = []
    for row in _tables[table]:
        ok = True
        for k, v in filters.items():
            if row.get(k) != v:
                ok = False
                break
        if ok:
            results.append(row)
    return results


def list_table(table: str, filters=None, sort_keys=("created_at", "id"),
               limit: int = None, offset: int = 0, predicate=None):
    """Sorted, paginated listing. Returns (items, total_count)."""
    rows = list(_tables[table])
    if filters:
        rows = [r for r in rows if all(r.get(k) == v for k, v in filters.items() if v is not None)]
    if predicate is not None:
        rows = [r for r in rows if predicate(r)]
    rows.sort(key=lambda r: tuple(r.get(k, "") for k in sort_keys))
    total = len(rows)
    if offset:
        rows = rows[offset:]
    if limit is not None:
        rows = rows[:limit]
    return rows, total


def all_rows(table: str):
    return list(_tables[table])


def delete_where(table: str, **filters):
    rows = _tables[table]
    keep = []
    deleted = []
    for r in rows:
        if all(r.get(k) == v for k, v in filters.items()):
            deleted.append(r)
        else:
            keep.append(r)
    _tables[table] = keep
    return deleted


def next_amendment_seq(lc_id: str) -> int:
    n = _lc_amendment_seq.get(lc_id, 0) + 1
    _lc_amendment_seq[lc_id] = n
    return n


def next_presentation_seq(lc_id: str) -> int:
    n = _lc_presentation_seq.get(lc_id, 0) + 1
    _lc_presentation_seq[lc_id] = n
    return n


def next_lc_number() -> str:
    global _lc_number_seq
    _lc_number_seq += 1
    year = _clock_now.year
    return f"LC-{year:04d}-{_lc_number_seq:06d}"
