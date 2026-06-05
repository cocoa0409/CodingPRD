"""In-memory data store for the Lab Results & Critical Value Notification API.

Every store starts empty on each fresh boot. The test harness restarts the
server via start.sh before every test, so there is no carry-over state.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, date, timedelta
from typing import Dict, Any, Optional


def new_uuid() -> str:
    return str(uuid.uuid4())


def wall_now_iso() -> str:
    """Wall-clock ISO-8601 UTC timestamp with three fractional digits.

    Used only for api_request_timestamp.
    Business-time uses the pinned logical clock — see now_iso().
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id() -> str:
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


# ---- entity stores (cleared at module load each fresh boot) ----------------

patients: Dict[str, Dict[str, Any]] = {}
clinicians: Dict[str, Dict[str, Any]] = {}
lab_orders: Dict[str, Dict[str, Any]] = {}
specimens: Dict[str, Dict[str, Any]] = {}
instruments: Dict[str, Dict[str, Any]] = {}
instrument_runs: Dict[str, Dict[str, Any]] = {}
results: Dict[str, Dict[str, Any]] = {}
critical_notifications: Dict[str, Dict[str, Any]] = {}
acknowledgement_receipts: Dict[str, Dict[str, Any]] = {}
retest_requests: Dict[str, Dict[str, Any]] = {}


# Logical clock (PRD §3.9). Tests pin via POST /_clock/set_current_utc.
# When not pinned, it falls back to wall clock.
_clock: Dict[str, Any] = {"current_utc": None}


def get_current_utc_dt() -> datetime:
    """Return the current logical clock as an aware UTC datetime."""
    s = _clock["current_utc"]
    if s is None:
        return datetime.now(timezone.utc)
    return parse_iso_dt(s)


def get_current_utc_iso() -> str:
    dt = get_current_utc_dt()
    return _dt_to_iso(dt)


def set_current_utc(iso: str) -> Dict[str, Any]:
    # Normalize and store as ISO with milliseconds precision.
    dt = parse_iso_dt(iso)
    _clock["current_utc"] = _dt_to_iso(dt)
    return {"current_utc": _clock["current_utc"]}


def _dt_to_iso(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


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
    ts = get_current_utc_iso()
    obj.setdefault("id", new_uuid())
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    return obj


def stamp_immutable(obj: Dict[str, Any]) -> Dict[str, Any]:
    """For AcknowledgementReceipt — only id + created_at."""
    obj.setdefault("id", new_uuid())
    obj["created_at"] = get_current_utc_iso()
    return obj


def bump(obj: Dict[str, Any]) -> Dict[str, Any]:
    obj["updated_at"] = get_current_utc_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj
