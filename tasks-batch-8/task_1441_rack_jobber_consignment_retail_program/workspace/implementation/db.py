"""In-memory data store and the logical clock (PRD Section 2.6).

Storage is in-memory ONLY. Every collection is a plain dict keyed by id.
Nothing is seeded, preloaded, or hardcoded at startup; the store begins empty
on every process boot and tests build all state via the API.

The system never consults wall-clock time (PRD Section 2.6): a logical clock
governs every temporal decision and every recorded timestamp. At startup the
logical clock reads exactly 2026-08-01T00:00:00Z.
"""
import datetime
import itertools
import uuid

# Logical clock default on server startup (PRD Section 2.6).
CLOCK_DEFAULT = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits, 'Z' suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_date(d):
    """ISO 8601 date string YYYY-MM-DD."""
    return d.strftime("%Y-%m-%d")


class Store:
    """Holds every entity collection and the logical clock for one process."""

    def __init__(self):
        self.programs = {}
        self.stores = {}
        self.agreements = {}
        self.products = {}
        self.space_allocations = {}
        self.price_directives = {}
        self.promotions = {}
        self.inventory_balances = {}
        self.routes = {}
        self.service_visits = {}
        self.scan_events = {}
        self.audit_counts = {}
        self.markdown_authorizations = {}
        self.settlement_statements = {}
        self.seasonal_sets = {}

        # The logical clock — the single instant for every temporal decision.
        self.clock = CLOCK_DEFAULT

        # Monotonic insertion sequence; stable tie-break for created_at ordering.
        self._seq = itertools.count(1)

    def new_id(self):
        # id is a server-minted UUID with no type prefix (PRD Section 2.4).
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)

    def now(self):
        return self.clock

    def now_iso(self):
        return fmt_dt(self.clock)

    def today(self):
        return self.clock.date()

    def today_str(self):
        return fmt_date(self.clock.date())


# Single global store instance, fresh on every process boot.
store = Store()
