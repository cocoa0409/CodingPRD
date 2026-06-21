"""In-memory data store and global clock.

Resets on every fresh process boot (the harness restarts the server before
every pytest test). No seeding at startup.
"""
from __future__ import annotations

import datetime as _dt
import secrets
import string
import threading
import uuid
from typing import Dict, Optional


# Per-process stores. Plain dicts keyed by id.
business_entities: Dict[str, dict] = {}
operating_agreements: Dict[str, dict] = {}
ein_applications: Dict[str, dict] = {}
registered_agents: Dict[str, dict] = {}
annual_reports: Dict[str, dict] = {}
foreign_qualifications: Dict[str, dict] = {}
boi_disclosures: Dict[str, dict] = {}
compliance_events: Dict[str, dict] = {}

# Insertion sequence so we can sort deterministically before created_at exists.
_seq_counter = 0
_seq_lock = threading.Lock()

# Server clock — pinned UTC instant. None means use wall-clock.
_clock_pinned_utc: Optional[_dt.datetime] = None

# Sequence used to mint deterministic EINs ("87-NNNNNNN").
_ein_counter = 0


def reset_all() -> None:
    """Clear all in-memory state. Used only on fresh process boot;
    not exposed via the API.
    """
    global _seq_counter, _clock_pinned_utc, _ein_counter
    business_entities.clear()
    operating_agreements.clear()
    ein_applications.clear()
    registered_agents.clear()
    annual_reports.clear()
    foreign_qualifications.clear()
    boi_disclosures.clear()
    compliance_events.clear()
    _seq_counter = 0
    _clock_pinned_utc = None
    _ein_counter = 0


def next_seq() -> int:
    global _seq_counter
    with _seq_lock:
        _seq_counter += 1
        return _seq_counter


def gen_uuid() -> str:
    return str(uuid.uuid4())


def gen_request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


# ---------- Clock ----------

def set_clock(iso_str: str) -> _dt.datetime:
    """Pin the server's notion of `now` to the supplied ISO 8601 UTC instant."""
    global _clock_pinned_utc
    dt = parse_iso8601_utc(iso_str)
    _clock_pinned_utc = dt
    return dt


def now_utc() -> _dt.datetime:
    """Return the current server clock UTC (pinned if set, else wall)."""
    if _clock_pinned_utc is not None:
        return _clock_pinned_utc
    return _dt.datetime.now(_dt.timezone.utc)


def iso_format(dt: _dt.datetime) -> str:
    """Format as ISO 8601 UTC with exactly 3 fractional digits, trailing 'Z'."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    else:
        dt = dt.astimezone(_dt.timezone.utc)
    micro = dt.microsecond
    millis = micro // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def parse_iso8601_utc(s: str) -> _dt.datetime:
    """Parse an ISO 8601 string into a tz-aware UTC datetime.

    Accepts trailing 'Z' or numeric offset; coerces to UTC.
    """
    if not isinstance(s, str) or not s:
        raise ValueError("invalid ISO 8601 string")
    raw = s.strip()
    # Python's fromisoformat handles "+00:00" but not "Z" (pre-3.11). Normalize:
    if raw.endswith("Z") or raw.endswith("z"):
        raw_norm = raw[:-1] + "+00:00"
    else:
        raw_norm = raw
    try:
        dt = _dt.datetime.fromisoformat(raw_norm)
    except ValueError as exc:
        raise ValueError(f"invalid ISO 8601: {s}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_dt.timezone.utc)


# ---------- EIN minting ----------

def next_ein() -> str:
    """Return deterministic EIN: 87-NNNNNNN where N is a zero-padded seq."""
    global _ein_counter
    _ein_counter += 1
    return f"87-{_ein_counter:07d}"
