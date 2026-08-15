"""In-memory data store and logical clock.

The store starts completely empty on every boot. Every entity is created
via the declared API surface; nothing is seeded at startup.
"""

import uuid
from datetime import datetime, timezone, date


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

class LogicalClock:
    """Server-side logical clock. Default before any set call:
    exactly 2026-08-01T00:00:00Z. Never falls back to wall-clock."""

    def __init__(self):
        self._current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._current

    def today(self):
        return self._current.date()

    def set(self, dt):
        self._current = dt


CLOCK = LogicalClock()


# ---------------------------------------------------------------------------
# Stores: dict keyed by id. Insertion order preserved (Python dicts) so
# created_at-ascending sort for lists is simply insertion order when
# created_at ties; we sort explicitly by (created_at, insertion seq).
# ---------------------------------------------------------------------------

class Store:
    def __init__(self):
        self.state_statute_profiles = {}
        self.payees = {}
        self.guardianship_cases = {}
        self.settlement_agreements = {}
        self.qualified_assignments = {}
        self.annuity_policies = {}
        self.payment_schedules = {}
        self.scheduled_payments = {}
        self.returned_payment_cases = {}
        self.payee_change_requests = {}
        self.transfer_petitions = {}
        self.death_claims = {}
        self.commutation_requests = {}
        self.escheatment_batches = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


DB = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Real wall-clock timestamp for created_at/updated_at metadata,
    ISO 8601 UTC with three fractional digits (milliseconds)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_date_iso():
    return CLOCK.today().isoformat()


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------

def base_entity():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": DB.next_seq(),
    }


def touch(entity):
    """Bump version and updated_at."""
    entity["version"] += 1
    entity["updated_at"] = now_iso()


def touch_meta_only(entity):
    """Refresh updated_at without a version bump (rarely used)."""
    entity["updated_at"] = now_iso()


# ---------------------------------------------------------------------------
# Date helpers (logical-clock based)
# ---------------------------------------------------------------------------

def parse_date(s):
    """Parse YYYY-MM-DD into a datetime.date. Raises ValueError on bad format."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    parts = s.split("-")
    if len(parts) != 3:
        raise ValueError("bad format")
    if len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
        raise ValueError("bad format")
    return date(int(parts[0]), int(parts[1]), int(parts[2]))


def add_years(d, years):
    """Anniversary date: same month/day `years` later. Feb 29 -> Feb 28 on
    non-leap years (standard anniversary convention)."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # Feb 29 -> Feb 28
        return d.replace(year=d.year + years, day=28)
