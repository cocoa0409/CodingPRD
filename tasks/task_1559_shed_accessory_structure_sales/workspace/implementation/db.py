"""In-memory data store. State resets on every process boot.

Holds entity dicts keyed by id, plus the logical clock. No persistence of any
kind: no SQLite, no JSON dump, no /tmp cache. The store starts empty at import
time and is populated exclusively through the declared API endpoints.
"""

from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.6)
# ---------------------------------------------------------------------------

CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

_clock = {"current_utc": CLOCK_DEFAULT}


def get_clock() -> str:
    """Current logical clock value as an ISO 8601 string."""
    return _clock["current_utc"]


def set_clock(to_iso8601: str) -> str:
    _clock["current_utc"] = to_iso8601
    return _clock["current_utc"]


def now_iso() -> str:
    """Current logical time, normalized to ISO 8601 UTC with 3 fractional digits."""
    dt = parse_iso(_clock["current_utc"])
    return format_iso(dt)


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 string (accepts trailing Z or explicit offset)."""
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


# ---------------------------------------------------------------------------
# Entity stores — keyed by id, all start empty
# ---------------------------------------------------------------------------

jurisdictions: dict = {}
models: dict = {}
customers: dict = {}
orders: dict = {}
site_assessments: dict = {}
permit_applications: dict = {}
rto_contracts: dict = {}
payments: dict = {}
service_tickets: dict = {}
