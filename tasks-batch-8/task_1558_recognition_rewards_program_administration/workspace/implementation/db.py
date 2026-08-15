"""In-memory data store and logical clock.

The store starts empty on every boot. No seeding of any entity happens here;
tests construct all preconditions through the declared API surface.
"""
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock (PRD section 2.5)
# ---------------------------------------------------------------------------

_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    """Current logical instant (aware UTC datetime)."""
    return _CLOCK


def today():
    return _CLOCK.date()


def set_clock(value):
    global _CLOCK
    _CLOCK = value


# ---------------------------------------------------------------------------
# Stores (dicts keyed by id; insertion-ordered)
# ---------------------------------------------------------------------------

programs = {}
departments = {}
employees = {}
budgets = {}
nominations = {}
awards = {}
vendors = {}
catalog_items = {}
orders = {}
tax_records = {}
accrual_runs = {}
abuse_flags = {}
anniversary_events = {}

# Ledger is an append-only list (immutable journal; chronological order is
# insertion order because the logical clock never moves backward).
ledger = []

# (program_id, tax_year) pairs already finalized.
finalized_tax_years = set()


def new_id():
    return str(uuid.uuid4())


def iso_ms(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_date(d):
    return d.isoformat()


def stamp(entity):
    """Set created_at/updated_at/version on a freshly built entity."""
    t = now()
    entity["created_at"] = t
    entity["updated_at"] = t
    entity["version"] = 1
    return entity


def touch(entity):
    """Mark a mutation: bump version and updated_at."""
    entity["version"] += 1
    entity["updated_at"] = now()
