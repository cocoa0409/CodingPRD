"""In-memory data store and clock/id/timestamp utilities.

Stores start EMPTY on every boot. Tests construct all preconditions via the
declared API surface. Nothing is seeded here.
"""
from __future__ import annotations

import random
import string
import uuid
from datetime import datetime, timezone
from typing import Any, Dict


# ---- id / request-id helpers -------------------------------------------------
def new_uuid() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    alphanum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphanum, k=20))


def _fmt_iso(dt: datetime) -> str:
    """ISO 8601 UTC with exactly three fractional digits and a 'Z' suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_now_iso() -> str:
    """Real wall-clock timestamp for created_at / updated_at audit fields."""
    return _fmt_iso(datetime.now(timezone.utc))


# ---- logical system clock ----------------------------------------------------
# Drives is_minor, submitted_at, verification_completed_at, occurred_at and SLA
# dates. Tests set it via POST /_clock/set_current_utc. Defaults to a stable
# instant so time-derived computations are deterministic before any set call.
class _Clock:
    def __init__(self) -> None:
        self.current_utc: str = "2025-01-01T00:00:00.000Z"

    def set(self, iso: str) -> None:
        self.current_utc = iso

    def now_iso(self) -> str:
        return self.current_utc


clock = _Clock()


# ---- stores (fresh & empty on each boot) -------------------------------------
applicants: Dict[str, Dict[str, Any]] = {}
applications: Dict[str, Dict[str, Any]] = {}
acceptance_agents: Dict[str, Dict[str, Any]] = {}
adjudicators: Dict[str, Dict[str, Any]] = {}
supporting_documents: Dict[str, Dict[str, Any]] = {}
photos: Dict[str, Dict[str, Any]] = {}
fee_assessments: Dict[str, Dict[str, Any]] = {}
appointments: Dict[str, Dict[str, Any]] = {}
acceptance_facilities: Dict[str, Dict[str, Any]] = {}
urgent_travel_counters: Dict[str, Dict[str, Any]] = {}
adjudication_decisions: Dict[str, Dict[str, Any]] = {}
status_events: Dict[str, Dict[str, Any]] = {}

# Monotonic sequence used as a secondary sort key so creation order is stable
# even when two records land in the same millisecond.
_seq_counter = {"n": 0}


def next_seq() -> int:
    _seq_counter["n"] += 1
    return _seq_counter["n"]
