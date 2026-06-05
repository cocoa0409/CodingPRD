"""In-memory data store for the Marina Slip Rental API.

Every store starts empty on each fresh boot. The test harness restarts the
server via start.sh before every test, so there is no carry-over state.
"""
from __future__ import annotations

import re
import threading
import uuid
from datetime import datetime, timezone, date
from typing import Any, Dict, Optional


# ---- ID + request helpers ---------------------------------------------------

def new_uuid() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


# ---- timestamp helpers ------------------------------------------------------


def now_wall_iso() -> str:
    """Wall-clock ISO 8601 UTC with three fractional digits.

    Used for the response envelope's api_request_timestamp only — this stays
    on real wall time so request stamps are unique and monotone even when the
    logical clock is pinned by tests.
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_format(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso_dt(s: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 datetime, returning a tz-aware UTC datetime.

    Accepts trailing 'Z' or explicit offset. Returns None for None / empty.
    Raises ValueError on malformed input.
    """
    if s is None or s == "":
        return None
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_iso_date(s: Optional[str]) -> Optional[date]:
    """Parse a strict YYYY-MM-DD calendar date. None for None/empty."""
    if s is None or s == "":
        return None
    if not isinstance(s, str) or not _DATE_RE.match(s):
        raise ValueError("invalid date")
    return date.fromisoformat(s)


_MMDD_RE = re.compile(r"^\d{2}-\d{2}$")


def parse_mmdd(s: Optional[str]) -> Optional[tuple]:
    """Parse a strict MM-DD calendar fragment to (month, day) tuple."""
    if s is None or s == "":
        return None
    if not isinstance(s, str) or not _MMDD_RE.match(s):
        raise ValueError("invalid MM-DD")
    m, d = int(s[:2]), int(s[3:])
    if not (1 <= m <= 12) or not (1 <= d <= 31):
        raise ValueError("invalid MM-DD month/day")
    # Validate the date is real (e.g. 02-30 should fail) using a leap year (2000)
    # so 02-29 is acceptable.
    try:
        date(2000, m, d)
    except ValueError:
        raise ValueError("invalid MM-DD date")
    return (m, d)


# ---- logical clock (PRD §2.10) ----------------------------------------------

# Initialised to a sensible epoch; tests overwrite via POST /_clock/set_current_utc.
_clock: Dict[str, Any] = {"current_utc": "2025-01-01T00:00:00.000Z"}


def get_current_utc() -> str:
    return _clock["current_utc"]


def set_current_utc(iso: str) -> str:
    _clock["current_utc"] = iso
    return iso


def now_logical_iso() -> str:
    """Server logical-clock ISO 8601 UTC (3 fractional digits).

    Used for entity created_at/updated_at and for state-machine side-effect
    timestamps (liveaboard_approved_at, requested_at, completed_at, dispatched_at)
    so that comparisons against logical-clock-derived deadlines stay consistent.
    """
    iso = get_current_utc()
    dt = parse_iso_dt(iso)
    if dt is None:
        return now_wall_iso()
    return iso_format(dt)


def now_logical_date() -> date:
    iso = get_current_utc()
    dt = parse_iso_dt(iso)
    assert dt is not None
    return dt.date()


def now_logical_dt() -> datetime:
    iso = get_current_utc()
    dt = parse_iso_dt(iso)
    assert dt is not None
    return dt


# ---- entity stores (cleared at module load each fresh boot) ----------------

marinas: Dict[str, Dict[str, Any]] = {}
slips: Dict[str, Dict[str, Any]] = {}
vessels: Dict[str, Dict[str, Any]] = {}
tenants: Dict[str, Dict[str, Any]] = {}
leases: Dict[str, Dict[str, Any]] = {}
pump_out_requests: Dict[str, Dict[str, Any]] = {}
tow_assist_events: Dict[str, Dict[str, Any]] = {}
transfer_waitlist: Dict[str, Dict[str, Any]] = {}


# Global mutation lock — every API mutation runs under this lock to make the
# request stream serializable, which keeps cascade side-effects, version bumps
# and computed-field re-aggregation observably atomic.
mutation_lock = threading.RLock()


# ---- common-field stamping helpers ------------------------------------------


def stamp_common(obj: Dict[str, Any]) -> Dict[str, Any]:
    ts = now_logical_iso()
    obj.setdefault("id", new_uuid())
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    return obj


def stamp_immutable(obj: Dict[str, Any]) -> Dict[str, Any]:
    """For append-only entities (TowAssistEvent): id + created_at only."""
    ts = now_logical_iso()
    obj.setdefault("id", new_uuid())
    obj["created_at"] = ts
    return obj


def bump(obj: Dict[str, Any]) -> Dict[str, Any]:
    obj["updated_at"] = now_logical_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj


def created_then_id(v: Dict[str, Any]):
    """Stable sort key used for default list ordering (PRD §2.3)."""
    return (v.get("created_at", ""), v.get("id", ""))
