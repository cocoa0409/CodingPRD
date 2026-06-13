"""Entity record helpers: common-field stamping and timestamp parsing.

Common fields per PRD §2.4:
  - id: server-minted UUID, no prefix
  - created_at: ISO8601 UTC (3 frac digits), fixed at creation
  - updated_at: ISO8601 UTC, refreshed on every mutation
  - version: integer, begins at 1 on creation, +1 on every mutation
LedgerEntry is the exception: only id + created_at (append-only).
"""
from datetime import datetime, timezone

import db


def stamp_new(record, with_version=True):
    """Add common system-managed fields to a freshly created record."""
    ts = db.now_iso()
    record["id"] = db.new_id()
    record["created_at"] = ts
    record["_seq"] = db.next_seq()  # internal ordering key, not serialized
    if with_version:
        record["updated_at"] = ts
        record["version"] = 1
    return record


def touch(record):
    """Mark a record mutated: refresh updated_at and bump version (PRD §2.4/§2.8)."""
    if "version" in record:
        record["updated_at"] = db.now_iso()
        record["version"] += 1


def iso_from_dt(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    u = dt.astimezone(timezone.utc)
    return u.strftime("%Y-%m-%dT%H:%M:%S.") + f"{u.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Accepts trailing 'Z' and offsets. Returns None on failure."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
