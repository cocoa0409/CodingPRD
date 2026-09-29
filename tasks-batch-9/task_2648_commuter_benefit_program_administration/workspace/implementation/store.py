"""In-memory data store, id minting, timestamps and the logical clock.

Storage is process-local Python dictionaries only.  The store starts completely
EMPTY on every boot: no entity is ever seeded, preloaded or hardcoded here.
Every row any caller sees was created through a declared endpoint.
"""

import threading
import uuid
from datetime import datetime, timedelta, timezone

# The logical clock's startup default, pinned by PRD 2.5.
LOGICAL_CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_lock = threading.RLock()


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


class Store:
    def __init__(self):
        self.employers = {}
        self.benefit_categories = {}
        self.employees = {}
        self.election_windows = {}
        self.benefit_accounts = {}
        self.ledger_entries = {}
        self.elections = {}
        self.transit_media = {}
        self.order_batches = {}
        self.media_orders = {}
        self.card_transactions = {}
        self.substantiation_claims = {}
        self.payroll_files = {}
        self.compliance_assessments = {}

        self.clock = LOGICAL_CLOCK_DEFAULT
        self._seq = 0
        self._last_ts = None

    # ------------------------------------------------------------- identity
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        with _lock:
            self._seq += 1
            return self._seq

    # ----------------------------------------------------------- timestamps
    def now(self):
        """Strictly increasing real-time UTC instant used for created_at/updated_at."""
        with _lock:
            raw = datetime.now(timezone.utc)
            now = raw.replace(microsecond=(raw.microsecond // 1000) * 1000)
            if self._last_ts is not None and now <= self._last_ts:
                now = self._last_ts + timedelta(milliseconds=1)
            self._last_ts = now
            return now

    def now_iso(self):
        return fmt_ts(self.now())

    # --------------------------------------------------------- logical clock
    def clock_now(self):
        return self.clock

    def clock_iso(self):
        return fmt_ts(self.clock)

    def set_clock(self, dt):
        self.clock = dt.astimezone(timezone.utc)


store = Store()


# --------------------------------------------------------------- row helpers
def stamp_new(row, versioned=True):
    """Attach the common identity fields to a brand new row."""
    row["id"] = store.new_id()
    row["created_at"] = store.now_iso()
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = store.next_seq()
    return row


def bump(row):
    """Record a mutation: refresh updated_at and advance version by exactly 1."""
    row["updated_at"] = store.now_iso()
    row["version"] = row.get("version", 1) + 1
    return row


def public(row):
    """Strip private bookkeeping keys before serialization."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def sort_key(row):
    return (row["created_at"], row["_seq"])


def sorted_rows(rows, newest_first=False):
    return sorted(rows, key=sort_key, reverse=newest_first)
