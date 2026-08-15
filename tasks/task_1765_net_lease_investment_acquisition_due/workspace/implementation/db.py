"""In-memory data store plus the logical clock.

Module-level dicts only — no disk, no external persistence. Every start.sh
re-invocation boots with empty state; nothing is seeded here or anywhere else.

The logical clock (PRD §2.6) starts at exactly 2026-08-01T00:00:00Z and never
falls back to wall-clock time. Every timestamp the server emits (created_at,
updated_at, executed_at, api_request_timestamp, ...) reads this logical clock
so test-driven clock advancement is fully deterministic.
"""

import random
import string
import uuid
from datetime import datetime, timezone

stores = {
    "deals": {},
    "tenants": {},
    "properties": {},
    "leases": {},
    "models": {},
    "psas": {},
    "milestones": {},
    "title_reviews": {},
    "title_exceptions": {},
    "eas": {},
    "pcas": {},
    "estoppels": {},
    "sndas": {},
    "financing": {},
    "statements": {},
    "prorations": {},
    "true_ups": {},
}

_seq = 0

# Logical clock (PRD §2.6) — startup default, never wall-clock.
_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def clock_now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def next_seq():
    """Monotonic creation-order counter backing created_at-ASC ordering even
    when two records share the same logical timestamp."""
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def render_dt(dt):
    """ISO 8601 UTC with three fractional digits (PRD §2.2/§2.4)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime/date string into an aware UTC datetime.
    Accepts trailing Z, numeric offsets, fractional seconds, and date-only."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if s.endswith(("Z", "z")):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    else:
        raise ValueError("not a datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_iso():
    return render_dt(clock_now())


def make_record(fields=None):
    """Record with the common system-managed fields of PRD §2.4."""
    rec = {"id": new_id(), "created_at": now_iso(), "_seq": next_seq()}
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    if fields:
        rec.update(fields)
    return rec


def make_line(fields=None):
    """Proration line record: common_fields=false — id + created_at only,
    no updated_at and no version (immutable line items, PRD §2.4)."""
    rec = {"id": new_id(), "created_at": now_iso(), "_seq": next_seq()}
    if fields:
        rec.update(fields)
    return rec


def pub(rec):
    """Public view of a record: internal underscore-prefixed keys stripped."""
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}
