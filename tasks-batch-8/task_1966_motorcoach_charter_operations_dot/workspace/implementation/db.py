"""In-memory data store. Empty on every boot."""

import uuid
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_logical_clock = _DEFAULT_CLOCK


def now_utc() -> datetime:
    return _logical_clock


def set_clock(to: datetime):
    global _logical_clock
    _logical_clock = to


def iso_now() -> str:
    return to_iso(now_utc())


def to_iso(dt: datetime) -> str:
    """Format datetime as ISO 8601 UTC with 3 fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 string into an aware UTC datetime."""
    if s is None:
        return None
    if not isinstance(s, str):
        raise ValueError("expected string")
    v = s.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------
customers = {}
vehicles = {}
drivers = {}
quotes = {}
orders = {}
trip_logs = {}
incidents = {}
maintenance_records = {}
breakdowns = {}
insurance_certificates = {}
safety_audits = {}

_cert_counter = [0]


def next_cert_number() -> str:
    _cert_counter[0] += 1
    return f"CERT-{_cert_counter[0]:08d}"
