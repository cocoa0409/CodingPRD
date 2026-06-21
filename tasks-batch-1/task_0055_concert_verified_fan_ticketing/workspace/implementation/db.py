"""In-memory data store for the Concert Verified Fan Ticketing API.

Every store starts empty on each fresh boot. The test harness restarts the
server via start.sh before every test, so there is no carry-over state.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional


def new_uuid() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    """Wall-clock ISO-8601 UTC timestamp with three fractional digits.

    Used for created_at / updated_at / api_request_timestamp.
    Business-time comparisons use the logical clock (get_current_utc).
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id() -> str:
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


# ---- entity stores (cleared at module load each fresh boot) ----------------

fans: Dict[str, Dict[str, Any]] = {}
events: Dict[str, Dict[str, Any]] = {}
price_tiers: Dict[str, Dict[str, Any]] = {}
queue_entries: Dict[str, Dict[str, Any]] = {}
orders: Dict[str, Dict[str, Any]] = {}
tickets: Dict[str, Dict[str, Any]] = {}
transfers: Dict[str, Dict[str, Any]] = {}
resale_listings: Dict[str, Dict[str, Any]] = {}


# ---- logical clock (PRD §3.9) ----------------------------------------------
# Defaults to a sensible epoch; tests overwrite via POST /_clock/set_current_utc.
_clock: Dict[str, Any] = {"current_utc": "2025-01-01T00:00:00.000Z"}


def get_current_utc() -> str:
    return _clock["current_utc"]


def now_dt() -> datetime:
    """Current logical UTC time as a tz-aware datetime."""
    return parse_iso_dt(_clock["current_utc"])


def set_current_utc(iso: str) -> None:
    _clock["current_utc"] = iso


# ---- monotonic sequence for created_at tie-breaking ------------------------
# created_at has millisecond precision; rapid creations within the same
# millisecond need a stable insertion order. We attach a monotonic _seq to
# every entity at creation and sort by (created_at, _seq).
_seq_state: Dict[str, int] = {"n": 0}


def next_seq() -> int:
    _seq_state["n"] += 1
    return _seq_state["n"]


# ---- helpers ----------------------------------------------------------------

def parse_iso_dt(s: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 datetime (UTC aware). Accepts trailing 'Z' or +00:00."""
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


def stamp_common(obj: Dict[str, Any]) -> Dict[str, Any]:
    ts = now_iso()
    obj.setdefault("id", new_uuid())
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    obj["_seq"] = next_seq()
    return obj


def bump(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Register a mutation: refresh updated_at and increment version."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj
