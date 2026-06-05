"""In-memory data store + id/time/clock helpers.

All stores start empty on every fresh boot; the test harness restarts this
process before every test, so there is no carry-over state and nothing is
seeded here.
"""
from __future__ import annotations

import random
import string
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3 calculation constants)
# ---------------------------------------------------------------------------
TIER1_DAYS = 3
TIER2_DAYS = 4
TIER1_RATE_CENTS = 5000
TIER2_RATE_CENTS = 8000
TIER3_RATE_CENTS = 12000

GATE_BUFFER_MIN = 30
EXCURSION_BAND_C = 2.0
MAX_NO_SHOWS = 3

CLOCK_EPOCH = "2026-01-01T00:00:00.000Z"


# ---------------------------------------------------------------------------
# id / wall-clock helpers
# ---------------------------------------------------------------------------
def new_uuid() -> str:
    return str(uuid.uuid4())


def wall_now_iso() -> str:
    """Real wall-clock ISO-8601 UTC timestamp with three fractional digits.

    Used for created_at/updated_at and for the response envelope timestamp.
    Distinct from the logical clock, which drives business-time evaluations.
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id() -> str:
    raw = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + raw


# ---------------------------------------------------------------------------
# logical clock (test-controllable; PRD §2.4)
# ---------------------------------------------------------------------------
_clock: Dict[str, Any] = {"current_utc": CLOCK_EPOCH}


def clock_now() -> str:
    return _clock["current_utc"]


def clock_set(value: str) -> None:
    _clock["current_utc"] = value


def clock_view() -> Dict[str, Any]:
    return {"current_utc": _clock["current_utc"]}


# ---------------------------------------------------------------------------
# stores — one dict per mutable entity, keyed by id
# ---------------------------------------------------------------------------
berths: Dict[str, Dict[str, Any]] = {}
vessels: Dict[str, Dict[str, Any]] = {}
berth_windows: Dict[str, Dict[str, Any]] = {}
containers: Dict[str, Dict[str, Any]] = {}
yard_slots: Dict[str, Dict[str, Any]] = {}
gate_appointments: Dict[str, Dict[str, Any]] = {}
customs_holds: Dict[str, Dict[str, Any]] = {}
reefer_readings: Dict[str, Dict[str, Any]] = {}
eirs: Dict[str, Dict[str, Any]] = {}
demurrage_invoices: Dict[str, Dict[str, Any]] = {}

# Monotonic sequence to break created_at ties deterministically when two
# records are created within the same wall-clock millisecond.
_seq = {"n": 0}


def next_seq() -> int:
    _seq["n"] += 1
    return _seq["n"]
