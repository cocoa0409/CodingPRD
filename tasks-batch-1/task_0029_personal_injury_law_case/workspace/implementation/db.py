"""In-memory data store for the Personal Injury Case Management API.

All stores start empty on each fresh boot. The test harness restarts the
server via start.sh before every test — there is no carry-over state.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional


# ---- ID / timestamp helpers -------------------------------------------------

def new_uuid() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    """Wall-clock ISO-8601 UTC timestamp with three fractional digits.

    Used for created_at / updated_at / api_request_timestamp.
    Business-time comparisons use clock_state['current_utc'] (logical clock).
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id() -> str:
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


# ---- entity stores (cleared at module load each fresh boot) -----------------

clients: Dict[str, Dict[str, Any]] = {}
cases: Dict[str, Dict[str, Any]] = {}
medical_providers: Dict[str, Dict[str, Any]] = {}
medical_records_requests: Dict[str, Dict[str, Any]] = {}
damages_items: Dict[str, Dict[str, Any]] = {}
medical_liens: Dict[str, Dict[str, Any]] = {}
demand_letters: Dict[str, Dict[str, Any]] = {}
settlement_offers: Dict[str, Dict[str, Any]] = {}
court_events: Dict[str, Dict[str, Any]] = {}
disbursements: Dict[str, Dict[str, Any]] = {}


# Singleton system clock (PRD §2.10). Defaults to a sensible epoch; tests
# overwrite via POST /_clock/set_current_utc.
_DEFAULT_CLOCK = "2025-01-01T00:00:00.000Z"
clock_state: Dict[str, Any] = {
    "id": "clock",
    "current_utc": _DEFAULT_CLOCK,
    "created_at": now_iso(),
}


def get_current_utc() -> str:
    return clock_state["current_utc"]


def set_current_utc(iso: str) -> Dict[str, Any]:
    clock_state["current_utc"] = iso
    return clock_state_view()


def clock_state_view() -> Dict[str, Any]:
    return {
        "id": clock_state["id"],
        "current_utc": clock_state["current_utc"],
        "created_at": clock_state["created_at"],
    }


# ---- ISO 8601 helpers -------------------------------------------------------

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


def current_clock_dt() -> datetime:
    return parse_iso_dt(get_current_utc())  # type: ignore[return-value]


def to_iso_z(dt: datetime) -> str:
    """Serialize a datetime back to the canonical ISO-8601 UTC form
    with three fractional digits and trailing 'Z'."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---- common-field helpers ---------------------------------------------------

def stamp_common(obj: Dict[str, Any]) -> Dict[str, Any]:
    # PRD §2.10: the system clock is the authoritative wall clock that every
    # time-sensitive guard reads from, including the offer 30-day expiry which
    # compares `created_at` to `current_utc`. created_at therefore must be
    # stamped from the logical clock, not a separate real wall-clock, or the
    # comparison straddles two clocks.
    ts = get_current_utc()
    obj.setdefault("id", new_uuid())
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    return obj


def bump(obj: Dict[str, Any]) -> Dict[str, Any]:
    obj["updated_at"] = get_current_utc()
    obj["version"] = obj.get("version", 1) + 1
    return obj
