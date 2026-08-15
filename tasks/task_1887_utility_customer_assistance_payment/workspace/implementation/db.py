"""In-memory data store + logical program clock (PRD §2.4).

The store starts EMPTY on every boot: no seeding, no preloading, nothing.
All state is constructed via the declared API surface.
"""

import uuid
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Datetime helpers — ISO 8601 UTC, three fractional digits (PRD §2.4).
# ---------------------------------------------------------------------------

def parse_datetime(s):
    """Parse an ISO-8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    """Full timestamp, milliseconds precision, Z suffix."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_date(d):
    """A calendar date rendered as midnight UTC with millisecond precision."""
    return d.strftime("%Y-%m-%dT00:00:00.000Z")


def date_to_str(d):
    return fmt_date(d)


def add_days(d, n):
    return d + timedelta(days=n)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

class LogicalClock:
    """Single logical program clock; never falls back to wall clock."""

    DEFAULT_ISO = "2026-08-01T00:00:00Z"

    def __init__(self):
        self._now = parse_datetime(self.DEFAULT_ISO)

    def now(self):
        return self._now

    def date(self):
        return self._now.date()

    def set(self, dt):
        self._now = dt

    def now_iso(self):
        return fmt_ts(self._now)

    def date_iso(self):
        return fmt_date(self._now.date())


CLOCK = LogicalClock()


# ---------------------------------------------------------------------------
# Stores: dicts keyed by id. Empty at boot, by contract.
# ---------------------------------------------------------------------------

accounts = {}
applications = {}
enrollments = {}
dpas = {}
payments = {}
forgiveness_credits = {}
certificates = {}
shutoff_orders = {}
funding_sources = {}
fund_allocations = {}
referrals = {}

_seq_counter = [0]


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Entity mutation helpers: version / updated_at bookkeeping (PRD §2.5, §2.9).
# ---------------------------------------------------------------------------

def touch(entity):
    """Mark an entity modified: version += 1, updated_at = logical clock."""
    entity["version"] += 1
    entity["updated_at"] = CLOCK.now()


def stamp_common(entity):
    entity["created_at"] = CLOCK.now()
    entity["updated_at"] = CLOCK.now()
    entity["version"] = 1
    entity["_seq"] = next_seq()
