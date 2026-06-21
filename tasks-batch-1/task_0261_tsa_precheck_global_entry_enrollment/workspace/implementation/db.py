"""In-memory data store, id/request-id helpers, and the deterministic clock.

Stores start EMPTY on every boot. The test harness restarts the process before
every test (per-test-server isolation), so there is no carry-over state. Nothing
is seeded here — tests build all preconditions through the declared API surface.
"""
from __future__ import annotations

import random
import string
import uuid
from datetime import datetime, timezone
from typing import Any, Dict


# ---- id / request-id helpers -------------------------------------------------
def new_uuid() -> str:
    """Server-minted UUID carrying no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    alphanum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphanum, k=20))


def new_ktn_value() -> str:
    """System-minted, opaque nine-character KTN string (PRD §3.6)."""
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=9))


def _fmt_iso(dt: datetime) -> str:
    """ISO 8601 UTC with exactly three fractional digits and a 'Z' suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_now_iso() -> str:
    """Real wall-clock timestamp for created_at / updated_at fields (PRD §2.4)."""
    return _fmt_iso(datetime.now(timezone.utc))


# ---- logical system clock (PRD §2.10) ---------------------------------------
# Drives expiry, no-show eligibility, and renewal-too-early checks. Tests set it
# via POST /_clock/set_current_utc. Defaults to a stable instant so time-derived
# computations are deterministic before any set call.
class _Clock:
    def __init__(self) -> None:
        self.current_dt: datetime = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def set(self, dt: datetime) -> None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self.current_dt = dt.astimezone(timezone.utc)

    def now(self) -> datetime:
        return self.current_dt

    def now_iso(self) -> str:
        return _fmt_iso(self.current_dt)


clock = _Clock()


def iso(dt: datetime) -> str:
    """Format an arbitrary datetime as ISO 8601 UTC with 3 fractional digits."""
    return _fmt_iso(dt)


# ---- stores (fresh & empty on each boot) -------------------------------------
programs: Dict[str, Dict[str, Any]] = {}
enrollment_centers: Dict[str, Dict[str, Any]] = {}
appointment_slots: Dict[str, Dict[str, Any]] = {}
applicants: Dict[str, Dict[str, Any]] = {}
applications: Dict[str, Dict[str, Any]] = {}
background_checks: Dict[str, Dict[str, Any]] = {}
appointments: Dict[str, Dict[str, Any]] = {}
biometric_captures: Dict[str, Dict[str, Any]] = {}
known_traveler_numbers: Dict[str, Dict[str, Any]] = {}
appeals: Dict[str, Dict[str, Any]] = {}
redress_cases: Dict[str, Dict[str, Any]] = {}
fee_transactions: Dict[str, Dict[str, Any]] = {}
audit_events: Dict[str, Dict[str, Any]] = {}


# Monotonic sequence used as a secondary sort key so creation order is stable
# even when two records land in the same millisecond.
_seq_counter = {"n": 0}


def next_seq() -> int:
    _seq_counter["n"] += 1
    return _seq_counter["n"]
