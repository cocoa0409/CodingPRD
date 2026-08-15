"""In-memory data store and logical clock for the School Threat Assessment API.

The store starts completely empty on every boot. Tests build all state via
the declared API surface. The logical clock starts at exactly
2026-08-01T00:00:00Z and never falls back to wall-clock time (PRD section 2.5).
"""

from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Entity stores (keyed by id). Start empty.
# ---------------------------------------------------------------------------

schools: dict[str, dict] = {}
threat_cases: dict[str, dict] = {}
interviews: dict[str, dict] = {}
risk_assessments: dict[str, dict] = {}
management_plans: dict[str, dict] = {}
referrals: dict[str, dict] = {}
check_ins: dict[str, dict] = {}
reentry_plans: dict[str, dict] = {}
documents: dict[str, dict] = {}
audit_events: dict[str, dict] = {}


# Monotonic insertion sequence for stable created_at tie-breaking. Because the
# logical clock stamps identical created_at values on many resources created
# between clock advances, a secondary sequence preserves insertion order.
_SEQ = itertools.count(1)


def next_seq() -> int:
    return next(_SEQ)


# ---------------------------------------------------------------------------
# Logical clock (test-driving). Never wall-clock.
# ---------------------------------------------------------------------------

CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"


def _default_clock_dt() -> datetime:
    return datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


_CLOCK = {"now": _default_clock_dt()}


def clock() -> datetime:
    return _CLOCK["now"]


def set_clock(dt: datetime) -> None:
    _CLOCK["now"] = dt


def clock_iso() -> str:
    return format_iso(_CLOCK["now"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def new_id() -> str:
    return str(uuid.uuid4())


def format_iso(dt: datetime) -> str:
    """ISO 8601 UTC, three fractional digits, trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_logical_iso() -> str:
    """All server-stamped resource timestamps derive from the logical clock."""
    return format_iso(_CLOCK["now"])


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 timestamp to an aware UTC datetime."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def touch(entity: dict) -> None:
    """Refresh updated_at (logical clock) and bump version on mutation."""
    entity["updated_at"] = now_logical_iso()
    entity["version"] = entity.get("version", 1) + 1


def stamp_new(entity: dict) -> dict:
    ts = now_logical_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def stamp_new_light(entity: dict) -> dict:
    """For CaseDocument / AuditEvent: only id + created_at (PRD section 2.4)."""
    entity["id"] = new_id()
    entity["created_at"] = now_logical_iso()
    entity["_seq"] = next_seq()
    return entity


def public(entity: dict) -> dict:
    """Strip internal bookkeeping fields from a stored entity."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}
