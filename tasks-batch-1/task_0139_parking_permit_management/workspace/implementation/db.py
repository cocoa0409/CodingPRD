"""In-memory data store for the Parking & Permit Management API.

Every store starts empty on each fresh boot. The test harness restarts the
server via start.sh before every test (`--isolation per-test-server`), so there
is no carry-over state. NOTHING is seeded here.
"""
from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


def now_iso() -> str:
    """Wall-clock ISO-8601 UTC timestamp with three fractional digits.

    Used for the response envelope's api_request_timestamp and for entity
    created_at / updated_at (PRD §2.4 — server-minted instants).
    """
    return iso_format(datetime.now(timezone.utc))


# ---- entity stores (cleared on every fresh boot at module load) ------------

garages: Dict[str, Dict[str, Any]] = {}
zones: Dict[str, Dict[str, Any]] = {}
spaces: Dict[str, Dict[str, Any]] = {}
rate_plans: Dict[str, Dict[str, Any]] = {}
event_pricing: Dict[str, Dict[str, Any]] = {}
permits: Dict[str, Dict[str, Any]] = {}
waitlist_entries: Dict[str, Dict[str, Any]] = {}
motorists: Dict[str, Dict[str, Any]] = {}
sessions: Dict[str, Dict[str, Any]] = {}
validations: Dict[str, Dict[str, Any]] = {}
merchants: Dict[str, Dict[str, Any]] = {}
citations: Dict[str, Dict[str, Any]] = {}
appeals: Dict[str, Dict[str, Any]] = {}
plate_reads: Dict[str, Dict[str, Any]] = {}

# Monotonic insertion counter for created_at ordering stability and for
# per-zone waitlist sequence assignment.
_seq_counter = itertools.count(1)


def next_seq() -> int:
    return next(_seq_counter)


# ---- settable server clock (PRD §3.3 / §3.5 / §3.8) ------------------------
# Drives permit expiry, validation redeemability, and LPR evaluation only.
# Defaults to wall-clock UTC until a test pins it via _clock/set_current_utc.
_clock: Dict[str, Any] = {"current_utc": None}


def set_current_utc(iso: str) -> None:
    _clock["current_utc"] = iso


def clock_now() -> datetime:
    """The server's notion of 'current UTC' for business-logic time checks."""
    if _clock["current_utc"] is None:
        return datetime.now(timezone.utc)
    dt = parse_iso_dt(_clock["current_utc"])
    return dt if dt is not None else datetime.now(timezone.utc)


# ---- time helpers ----------------------------------------------------------


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


def iso_format(dt: datetime) -> str:
    """Format a datetime into ISO-8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def plus_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


# ---- common-field stamping (PRD §2.4) --------------------------------------


def stamp_common(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Stamp id, created_at, updated_at, version. Full-common-fields entities."""
    ts = now_iso()
    obj.setdefault("id", new_uuid())
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    obj["_seq"] = next_seq()
    return obj


def stamp_immutable(obj: Dict[str, Any]) -> Dict[str, Any]:
    """For PlateRead — only id + created_at; no updated_at / version (PRD §2.4)."""
    obj.setdefault("id", new_uuid())
    obj["created_at"] = now_iso()
    obj["_seq"] = next_seq()
    return obj


def bump(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Refresh updated_at + increment version (every mutation, PRD §2.4/§2.7)."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj
