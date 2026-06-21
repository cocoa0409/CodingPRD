"""In-memory data store.

Every store starts EMPTY on each fresh boot. Tests build all preconditions via
the declared API surface. Nothing is seeded, preloaded, or hardcoded here.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Identifiers and timestamps
# ---------------------------------------------------------------------------

def new_uuid() -> str:
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    """Request id starting with 'req_' followed by alphanumeric chars (PRD §2.2)."""
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


def format_iso(dt: datetime) -> str:
    """ISO 8601 UTC with exactly three fractional digits and a 'Z' suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# Backwards-compatible private alias.
_format_iso = format_iso


def now_iso() -> str:
    """Wall-clock UTC timestamp used for created_at / updated_at / meta."""
    return _format_iso(datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Logical clock (test-driving; drives all temporal business comparisons)
# ---------------------------------------------------------------------------

class _LogicalClock:
    """Server logical clock (PRD §3.11).

    Used for: referral expiry, the no-show end-time gate, and vaccine spacing.
    Defaults to real wall-clock time until a test sets it.
    """

    def __init__(self) -> None:
        self._current: datetime = datetime.now(timezone.utc)

    def now(self) -> datetime:
        return self._current

    def set_from_iso(self, iso: str) -> datetime:
        self._current = parse_iso(iso)
        return self._current

    def current_iso(self) -> str:
        return _format_iso(self._current)


clock = _LogicalClock()


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 instant (accepts trailing 'Z') into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Stores — cleared on every fresh boot (module load)
# ---------------------------------------------------------------------------

providers: Dict[str, Dict[str, Any]] = {}
patients: Dict[str, Dict[str, Any]] = {}
cpt_codes: Dict[str, Dict[str, Any]] = {}
visits: Dict[str, Dict[str, Any]] = {}
charge_lines: Dict[str, Dict[str, Any]] = {}
prescriptions: Dict[str, Dict[str, Any]] = {}
referrals: Dict[str, Dict[str, Any]] = {}
portal_accounts: Dict[str, Dict[str, Any]] = {}
hedis_measures: Dict[str, Dict[str, Any]] = {}

# Per-patient recorded payments (sum of amount_cents) — backing data for the
# outstanding-balance derived field. Not an exposed entity.
patient_payments: Dict[str, int] = {}


# ---------------------------------------------------------------------------
# Common system fields
# ---------------------------------------------------------------------------

def stamp_create(record: Dict[str, Any], versioned: bool = True) -> Dict[str, Any]:
    """Attach common system fields on creation (PRD §2.4)."""
    ts = now_iso()
    record["id"] = new_uuid()
    record["created_at"] = ts
    if versioned:
        record["updated_at"] = ts
        record["version"] = 1
    return record


def touch(record: Dict[str, Any]) -> None:
    """Mutate common fields on any change (PRD §2.4): bump updated_at + version."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 0) + 1
