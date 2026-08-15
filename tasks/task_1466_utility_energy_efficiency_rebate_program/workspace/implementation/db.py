"""In-memory data store and logical program clock.

The store starts empty on every boot — no seeding of any kind. All
date/time-sensitive logic reads the logical clock, never wall-clock time.
"""
import itertools
import uuid
from datetime import datetime, timezone

# Fixed startup default per PRD section 2.4.
START_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.program_years = {}
        self.measures = {}
        self.trade_allies = {}
        self.applications = {}
        self.line_items = {}
        self.savings_claims = {}
        self.inspections = {}
        self.adjustments = {}
        self.fraud_flags = {}
        self._seq = itertools.count(1)
        self.clock = START_CLOCK

    def next_seq(self):
        return next(self._seq)


store = Store()


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def format_dt(dt):
    """ISO 8601 UTC timestamp with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    """Current logical-clock timestamp, ISO 8601 UTC, 3 fractional digits."""
    return format_dt(store.clock)


def today():
    """Current logical-clock calendar date."""
    return store.clock.astimezone(timezone.utc).date()


def base_fields():
    """Standard system-managed quartet plus internal ordering sequence."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }


def light_fields():
    """SavingsClaim / FraudFlag: only id and created_at."""
    return {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": store.next_seq(),
    }
