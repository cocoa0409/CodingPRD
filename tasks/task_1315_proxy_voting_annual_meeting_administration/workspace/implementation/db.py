"""In-memory data store for the Proxy Voting & Annual Meeting Administration API.

The store starts completely empty on every boot. Tests build all state via
the declared API surface.

The logical clock (PRD §2.4) starts at exactly 2026-08-01T00:00:00Z and is the
ONLY source of timestamps: created_at, updated_at, filed_at, the convene-time
comparison, and the response-envelope request timestamp all read it. The server
never falls back to wall-clock time.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Entity stores (keyed by id)
# ---------------------------------------------------------------------------

meetings: dict[str, dict] = {}
accounts: dict[str, dict] = {}
broker_searches: dict[str, dict] = {}
distributions: dict[str, dict] = {}
proposals: dict[str, dict] = {}
votes: dict[str, dict] = {}
sessions: dict[str, dict] = {}
questions: dict[str, dict] = {}
challenges: dict[str, dict] = {}
campaigns: dict[str, dict] = {}
certifications: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_CLOCK_DEFAULT = "2026-08-01T00:00:00Z"


def canonicalize_ts(value: str) -> str:
    """Normalize an ISO 8601 timestamp to UTC with three fractional digits."""
    text = value.strip()
    if text.endswith("Z"):
        dt = datetime.fromisoformat(text[:-1] + "+00:00")
    else:
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


_current_utc: str = canonicalize_ts(_CLOCK_DEFAULT)


def get_current_utc() -> str:
    return _current_utc


def set_current_utc(value: str) -> None:
    global _current_utc
    _current_utc = canonicalize_ts(value)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_seq_counter = 0


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    """All system timestamps are sourced from the logical clock (PRD §2.4/§2.5)."""
    return get_current_utc()


def stamp_new(entity: dict) -> dict:
    """Assign id/created_at/updated_at/version and an internal creation-order
    sequence number (_seq). _seq is never serialized; it is the deterministic
    tie-break for entities created at the same logical instant."""
    global _seq_counter
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    _seq_counter += 1
    entity["_seq"] = _seq_counter
    return entity


def touch(entity: dict) -> None:
    """Refresh updated_at and bump version on a mutated entity.

    _seq is intentionally left unchanged: it records creation order, which
    created_at-ascending list sorts and householding representative selection
    rely on as their tie-break."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1
