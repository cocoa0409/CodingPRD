"""In-memory data store. Starts empty on every boot — no seeding.

All entities live in module-level dicts keyed by UUID string ids.
The logical clock lives here too; it starts at exactly
2026-08-01T00:00:00Z and only moves via POST /_clock/set_current_utc.
"""

import datetime as _dt
import uuid


def new_id() -> str:
    return str(uuid.uuid4())


# Logical clock ---------------------------------------------------------------
_CLOCK_START = _dt.datetime(2026, 8, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)
_current_utc = _CLOCK_START


def get_clock() -> _dt.datetime:
    return _current_utc


def set_clock(to: _dt.datetime) -> _dt.datetime:
    global _current_utc
    _current_utc = to
    return _current_utc


def now_iso() -> str:
    """Current logical-clock instant as ISO 8601 UTC with three fractional
    digits, e.g. 2026-08-01T00:00:00.000Z."""
    return iso_format(get_clock())


def wall_iso() -> str:
    """Wall-clock timestamp (used only for meta.api_request_timestamp)."""
    return iso_format(_dt.datetime.now(_dt.timezone.utc))


def iso_format(dt: _dt.datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    dt = dt.astimezone(_dt.timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


def parse_iso(value):
    """Parse an ISO-8601 datetime string into an aware UTC datetime.

    Accepts trailing 'Z' or explicit offsets. Returns None on failure.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = _dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_dt.timezone.utc)


# Entity stores ---------------------------------------------------------------
creators = {}
brands = {}
briefs = {}
pitches = {}
deals = {}
deliverables = {}
disclosure_checks = {}
performance_reports = {}
invoices = {}
payouts = {}
disputes = {}
reshoots = {}
