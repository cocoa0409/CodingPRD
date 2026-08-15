"""In-memory data store for the Specialty Pharmacy Hub API.

The store starts completely empty on every boot. No entity is seeded,
preloaded, or hardcoded anywhere in the codebase. All entities are built
exclusively through the declared API surface.
"""

import uuid
from datetime import datetime, timezone, timedelta


class Store:
    """In-memory storage: dictionaries keyed by entity id."""

    def __init__(self):
        self.drug_programs = {}
        self.foundation_pools = {}
        self.enrollments = {}
        self.benefits_investigations = {}   # id -> BI; also enrollment_id indexed
        self.prior_authorizations = {}
        self.copay_assistances = {}
        self.shipments = {}
        self.nurse_visits = {}
        self.adverse_events = {}
        self.outcome_reports = {}
        # Logical clock: starts at exactly 2026-08-01T00:00:00Z, never
        # falls back to wall-clock time.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()


def new_id():
    """Mint a server-generated UUID with no type prefix."""
    return str(uuid.uuid4())


def now_iso():
    """Current wall-clock timestamp for created_at/updated_at fields.

    Format: ISO 8601 UTC with three fractional digits (milliseconds).
    Note: created_at/updated_at are wall-clock per PRD 2.4 (they are
    system-managed audit fields); the *logical clock* governs only
    time-dependent business rules (PDC windows, funding windows, etc.).
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def logical_now():
    """The server's logical clock (datetime, tz-aware UTC)."""
    return store.clock


def logical_today():
    """Current logical clock date (datetime.date)."""
    return store.clock.date()


def set_logical_clock(iso_str):
    """Advance the logical clock to the supplied ISO8601 UTC instant."""
    dt = _parse_iso_datetime(iso_str)
    if dt is None:
        raise ValueError("unparseable datetime")
    store.clock = dt
    return store.clock


def _parse_iso_datetime(s):
    """Parse an ISO8601 datetime string to a tz-aware UTC datetime.

    Accepts trailing 'Z' or explicit offsets. Returns None on failure.
    """
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if not txt:
        return None
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_iso_date(s):
    """Parse a YYYY-MM-DD date string. Returns None on failure."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    try:
        # Strict shape check: fromisoformat in modern Python is lenient
        # about some forms; require exactly YYYY-MM-DD.
        parts = txt.split("-")
        if len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
            return None
        from datetime import date
        return date.fromisoformat(txt)
    except ValueError:
        return None
