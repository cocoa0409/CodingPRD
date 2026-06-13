"""In-memory data store, ledger clock, id/timestamp helpers.

Storage is purely in-process dicts keyed by id. No persistence, no seeding —
every entity is constructed by tests via the declared API surface. A fresh
process (each start.sh re-invocation) starts with an empty store.
"""
import uuid
import random
import string
from datetime import datetime, timezone, date


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.customers = {}
        self.applications = {}
        self.accounts = {}
        self.account_owners = {}
        self.apy_tiers = {}
        self.transactions = {}
        self.fee_assessments = {}
        self.stop_payments = {}
        self.ach_originations = {}
        self.ach_legs = {}
        self.interest_postings = {}
        self.escheat_events = {}

        # Monotonic insertion sequence for stable created_at ordering when
        # multiple resources share the same (possibly frozen) clock instant.
        self._seq = 0

        # The ledger clock instant. Defaults to a fixed epoch so that every
        # date-driven rule is deterministic even before a test sets the clock.
        self._clock = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def next_seq(self):
        self._seq += 1
        return self._seq

    # --- ledger clock ---
    def now(self):
        """Ledger clock instant (drives timestamps + all date-based rules)."""
        return self._clock

    def clock_date(self):
        """Date component of the ledger clock (PRD §2.5)."""
        return self._clock.date()

    def set_clock(self, dt):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._clock = dt.astimezone(timezone.utc)


db = Store()


def reset_store():
    global db
    db = Store()


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    """Request id starting with req_ (PRD §2.2)."""
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.4)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso(db.now())


def clock_date_iso():
    """Current ledger clock date as ISO YYYY-MM-DD string."""
    return db.clock_date().isoformat()


def parse_date(s):
    """Parse an ISO date (YYYY-MM-DD) or full ISO instant into a date object."""
    if s is None:
        return None
    s = str(s)
    # Accept full ISO 8601 instants too; take the date component.
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        # Fallback to datetime parse for instants with offsets/Z.
        cleaned = s.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned).date()


def days_between(d1, d2):
    """Whole-day calendar difference d2 - d1 (PRD §2.5)."""
    return (d2 - d1).days
