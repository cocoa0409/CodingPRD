"""In-memory data store, logical clock, id/timestamp helpers. No disk persistence.

The store starts empty on every boot — nothing is seeded at startup. Every
entity is created through the declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

# The logical clock: starts exactly at 2026-08-01T00:00:00Z and never falls
# back to wall-clock. Rebound only by the /_clock/set_current_utc endpoint.
LOGICAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_seq_counter = itertools.count(1)


class Store:
    """All entity tables. Instantiated empty; nothing is seeded at startup."""

    def __init__(self):
        self.funds = {}
        self.share_classes = {}
        self.securities = {}
        self.positions = {}
        self.price_observations = {}
        self.nav_records = {}
        self.expense_accruals = {}
        self.waiver_agreements = {}
        self.waiver_ledger_entries = {}
        self.distributions = {}
        self.reconciliation_breaks = {}
        self.fee_invoices = {}
        self.regulatory_filings = {}


store = Store()


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


def _fmt_ms(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def logical_now():
    """Logical-clock instant as ISO 8601 UTC with three fractional digits."""
    return _fmt_ms(LOGICAL_CLOCK)


def request_now():
    """Wall-clock timestamp for the response meta block (3 fractional digits)."""
    return _fmt_ms(datetime.now(timezone.utc))


def clock_today():
    """The logical clock's UTC calendar date."""
    return LOGICAL_CLOCK.date()


def set_clock(dt):
    global LOGICAL_CLOCK
    LOGICAL_CLOCK = dt


def touch(entity):
    """Refresh updated_at and bump version on a mutable entity."""
    entity["updated_at"] = logical_now()
    entity["version"] = entity.get("version", 1) + 1


def new_common(entity):
    """Stamp common system fields on a freshly created entity."""
    entity["created_at"] = logical_now()
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def new_ledger_row(entity):
    """Waiver ledger entries carry only id + created_at (no updated_at/version)."""
    entity["created_at"] = logical_now()
    entity["_seq"] = next_seq()
    return entity
