"""In-memory data store for the Home Warranty Service API.

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

    Used only for api_request_timestamp in the response envelope. Entity
    created_at / updated_at use the logical clock (now_logical_iso) so that
    aggregate-window filters (which compare created_at against
    coverage_start_utc/coverage_end_utc — both stamped from the logical clock)
    stay consistent regardless of when in wall-clock time the test invokes them.
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_logical_iso() -> str:
    """Server logical-clock timestamp (ISO-8601 UTC, three fractional digits).

    All entity created_at/updated_at use this. The logical clock is settable via
    POST /_clock/set, and it drives every time comparison in §3 business logic
    — coverage windows, return-visit windows, dispatch-future check, renewal
    eligibility — so anchoring entity timestamps to it keeps the test harness's
    timeline self-consistent.
    """
    iso = get_current_utc()
    dt = parse_iso_dt(iso)
    if dt is None:
        # Fallback: wall clock (should never happen — _clock is always set).
        return now_iso()
    return iso_format(dt)


def new_request_id() -> str:
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


# ---- entity stores (cleared at module load each fresh boot) ----------------

contract_packages: Dict[str, Dict[str, Any]] = {}
customers: Dict[str, Dict[str, Any]] = {}
contracts: Dict[str, Dict[str, Any]] = {}
covered_items: Dict[str, Dict[str, Any]] = {}
claim_tickets: Dict[str, Dict[str, Any]] = {}
dispatches: Dict[str, Dict[str, Any]] = {}
renewal_reminders: Dict[str, Dict[str, Any]] = {}


# Logical clock (PRD §3.9). Defaults to a sensible epoch; tests overwrite via
# POST /_clock/set.
_clock: Dict[str, Any] = {"current_utc": "2025-01-01T00:00:00.000Z"}


def get_current_utc() -> str:
    return _clock["current_utc"]


def set_current_utc(iso: str) -> Dict[str, Any]:
    _clock["current_utc"] = iso
    return {"current_utc": iso}


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


def iso_format(dt: datetime) -> str:
    """Format a datetime back into ISO-8601 UTC w/ three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def stamp_common(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Stamp id, created_at, updated_at, version. Common-fields entities only.

    Timestamps come from the logical clock (now_logical_iso) so that aggregate
    filters comparing created_at to coverage_start_utc/coverage_end_utc work
    consistently — both reference points come from the same clock.
    """
    ts = now_logical_iso()
    obj.setdefault("id", new_uuid())
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    return obj


def stamp_immutable(obj: Dict[str, Any]) -> Dict[str, Any]:
    """For RenewalReminder — only id + created_at; no version/updated_at."""
    obj.setdefault("id", new_uuid())
    obj["created_at"] = now_logical_iso()
    return obj


def bump(obj: Dict[str, Any]) -> Dict[str, Any]:
    obj["updated_at"] = now_logical_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj
