"""In-memory data store for the Wedding RSVP & Gift Registry API.

Every store starts empty on each fresh boot. The test harness restarts the
server via start.sh before every test, so there is no carry-over state.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional


def new_uuid() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    """ISO-8601 UTC timestamp with three fractional digits, suffix 'Z'.

    This is the wall-clock stamp used for created_at / updated_at fields.
    Business time comparisons (rsvp_deadline_at, ceremony_at, sent_at) use
    the logical clock from get_current_utc().
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id() -> str:
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


def new_token() -> str:
    """Opaque invitation token (URL-safe)."""
    return secrets.token_urlsafe(24)


# ---- entity stores (cleared at module load each fresh boot) ----------------

weddings: Dict[str, Dict[str, Any]] = {}
meal_options: Dict[str, Dict[str, Any]] = {}
tables: Dict[str, Dict[str, Any]] = {}
guests: Dict[str, Dict[str, Any]] = {}
plus_ones: Dict[str, Dict[str, Any]] = {}
seating_assignments: Dict[str, Dict[str, Any]] = {}
registry_items: Dict[str, Dict[str, Any]] = {}
purchases: Dict[str, Dict[str, Any]] = {}
thank_you_notes: Dict[str, Dict[str, Any]] = {}

# Logical clock (PRD §2.10). Defaults to epoch; tests overwrite via /_clock.
_clock: Dict[str, Any] = {"current_utc": "1970-01-01T00:00:00.000Z"}


def get_current_utc() -> str:
    return _clock["current_utc"]


def set_current_utc(iso: str) -> None:
    _clock["current_utc"] = iso


def parse_iso(s: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 datetime string into an aware UTC datetime.

    Accepts trailing 'Z' or explicit +00:00 offset.
    Returns None when input is None/empty.
    Raises ValueError when input is malformed.
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


def stamp_common(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Initialise the four common fields on a freshly-created entity row."""
    ts = now_iso()
    obj.setdefault("id", new_uuid())
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    return obj


def bump(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Advance updated_at and version on a mutated entity row."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj
