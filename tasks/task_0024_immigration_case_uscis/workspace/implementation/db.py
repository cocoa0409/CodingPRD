"""In-memory data store for the USCIS Case Management API.

Every store starts empty on each fresh boot. The test harness restarts the
server via start.sh before every test, so there is no carry-over state.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, date, timedelta
from typing import Dict, Any, Optional


def new_uuid() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    """Wall-clock ISO-8601 UTC timestamp with three fractional digits.

    Used for created_at / updated_at / api_request_timestamp.
    Business-time comparisons use ClockState.current_utc (the logical clock).
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id() -> str:
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


# ---- entity stores (cleared at module load each fresh boot) ----------------

applicants: Dict[str, Dict[str, Any]] = {}
attorneys: Dict[str, Dict[str, Any]] = {}
cases: Dict[str, Dict[str, Any]] = {}
biometrics: Dict[str, Dict[str, Any]] = {}
rfes: Dict[str, Dict[str, Any]] = {}
interviews: Dict[str, Dict[str, Any]] = {}
visa_bulletin: Dict[str, Dict[str, Any]] = {}
case_events: Dict[str, Dict[str, Any]] = {}


# Logical clock (PRD §2.5). Defaults to a sensible epoch; tests overwrite via
# POST /uscis/_clock/set_current_utc.
_clock: Dict[str, Any] = {"id": "clock", "current_utc": "2025-01-01T00:00:00.000Z"}


def get_current_utc() -> str:
    return _clock["current_utc"]


def set_current_utc(iso: str) -> Dict[str, Any]:
    _clock["current_utc"] = iso
    return dict(_clock)


def clock_state() -> Dict[str, Any]:
    return dict(_clock)


# Officer round-robin pool (assigned at file time) ----------------------------
# A small, deterministic pool of opaque officer ids. round_robin_officer()
# returns the next one in sequence; the pool itself does not need persistence
# because each fresh boot only matters for the duration of one test.
_OFFICER_POOL = [
    "officer-001",
    "officer-002",
    "officer-003",
    "officer-004",
]
_officer_idx: Dict[str, int] = {"i": 0}


def round_robin_officer() -> str:
    i = _officer_idx["i"] % len(_OFFICER_POOL)
    _officer_idx["i"] = (i + 1) % len(_OFFICER_POOL)
    return _OFFICER_POOL[i]


# Receipt-number sequence ----------------------------------------------------
# Receipt format: <SC>YY<DDD>NNNNN — 3-letter service-center code, 2-digit
# year, 3-digit day-of-year, 5-digit monotonic sequence. We rotate through
# the service-center codes for variety and keep a shared sequence counter.
_SERVICE_CENTERS = ["NBC", "MSC", "SRC", "EAC", "WAC", "LIN", "YSC", "NSC", "VSC", "TSC"]
_receipt_state: Dict[str, int] = {"sc_idx": 0, "seq": 0}


def mint_receipt_number(file_date_iso: str) -> str:
    """Mint a new 13-char receipt number based on file_date.

    file_date_iso: 'YYYY-MM-DD'.
    Returns: <SC>YY<DDD>NNNNN where YY=last-two-digits of year,
    DDD=day-of-year zero-padded, NNNNN=monotonic sequence.
    """
    d = date.fromisoformat(file_date_iso)
    sc = _SERVICE_CENTERS[_receipt_state["sc_idx"] % len(_SERVICE_CENTERS)]
    _receipt_state["sc_idx"] = (_receipt_state["sc_idx"] + 1) % len(_SERVICE_CENTERS)
    _receipt_state["seq"] += 1
    seq = _receipt_state["seq"] % 100000
    yy = d.year % 100
    doy = (d - date(d.year, 1, 1)).days + 1
    return f"{sc}{yy:02d}{doy:03d}{seq:05d}"


# ---- helpers ----------------------------------------------------------------

def parse_iso_dt(s: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 datetime (UTC aware). Accepts trailing 'Z' or +00:00.

    Returns None for None/empty. Raises ValueError on malformed input.
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


def parse_iso_date(s: Optional[str]) -> Optional[date]:
    if s is None or s == "":
        return None
    if not isinstance(s, str):
        raise ValueError("not a string")
    return date.fromisoformat(s[:10])


def stamp_common(obj: Dict[str, Any]) -> Dict[str, Any]:
    ts = now_iso()
    obj.setdefault("id", new_uuid())
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    return obj


def stamp_immutable(obj: Dict[str, Any]) -> Dict[str, Any]:
    """For VisaBulletinEntry and CaseEvent — only id + created_at."""
    obj.setdefault("id", new_uuid())
    obj["created_at"] = now_iso()
    return obj


def bump(obj: Dict[str, Any]) -> Dict[str, Any]:
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj
