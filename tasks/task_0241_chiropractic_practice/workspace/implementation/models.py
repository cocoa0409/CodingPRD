"""Record creation, common-field management, serialization, and clock access.

Common fields (PRD §2.4):
  - id: UUID, no prefix
  - created_at / updated_at: ISO 8601 UTC, three fractional digits
  - version: integer, starts at 1, +1 per mutation
LedgerEntry and PracticeClock are exceptions: only id + created_at (PRD §2.4).
"""
from datetime import datetime, timezone

import db


def new_record(fields, common=True):
    """Build a record dict with system-managed common fields.

    Stores a private `_seq` for stable creation-order sorting, and an internal
    `_entity` marker is set by callers if needed.
    """
    ts = db.now_iso()
    rec = dict(fields)
    rec["id"] = db.new_id()
    rec["created_at"] = ts
    rec["_seq"] = db.next_seq()
    if common:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version (PRD §2.4)."""
    rec["updated_at"] = db.now_iso()
    if "version" in rec:
        rec["version"] += 1


# Fields never exposed to clients.
_INTERNAL = {"_seq", "_applied_to_deductible_cents"}


def serialize(rec):
    """Strip internal fields for the wire."""
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if k not in _INTERNAL}


def serialize_list(recs):
    return [serialize(r) for r in recs]


def _parse_iso(s):
    """Parse an ISO 8601 datetime string to an aware UTC datetime."""
    if s is None:
        return None
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_now():
    """Current practice-clock instant as an aware UTC datetime.

    Falls back to real wall-clock UTC if the clock was never set.
    """
    cur = db.practice_clock.get("current_utc")
    if cur is None:
        return datetime.now(timezone.utc)
    return _parse_iso(cur)
