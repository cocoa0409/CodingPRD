"""In-memory store, logical clock and identity helpers.

Everything lives in process memory: re-invoking start.sh wipes every byte of
state.  Nothing is seeded, preloaded or hardcoded — the store starts empty and
every entity is built through the declared endpoints.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.6: the logical clock's startup value is exactly 2026-08-01T00:00:00Z.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

TABLES = (
    "fee_schedules",
    "alarm_companies",
    "alarm_sites",
    "site_contacts",
    "alarm_systems",
    "alarm_permits",
    "dispatch_requests",
    "false_alarm_incidents",
    "hearing_dockets",
    "appeals",
    "suspension_orders",
    "penalty_invoices",
    "payment_records",
    "payment_allocations",
    "compliance_reports",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in TABLES:
            setattr(self, name, {})
        self.clock = CLOCK_START
        self.permit_seq = 0
        self.invoice_seq = 0
        self.receipt_seq = 0
        self._row_counter = itertools.count(1)

    # -- ordering tiebreaker ------------------------------------------------
    def next_row_seq(self):
        return next(self._row_counter)

    def next_permit_number(self):
        self.permit_seq += 1
        return "AP-%06d" % self.permit_seq

    def next_invoice_number(self):
        self.invoice_seq += 1
        return "INV-%06d" % self.invoice_seq

    def next_receipt_number(self):
        self.receipt_seq += 1
        return "RCT-%06d" % self.receipt_seq


store = Store()


# ---------------------------------------------------------------------------
# clock / time helpers
# ---------------------------------------------------------------------------

def now():
    return store.clock


def set_clock(dt):
    store.clock = dt


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def days(n):
    return timedelta(days=n)


def add_days(dt, n):
    return dt + timedelta(days=n)


def whole_days_between(later, earlier):
    """Whole days = floor of elapsed UTC seconds / 86400, negatives clamped to 0."""
    if later is None or earlier is None:
        return 0
    secs = (later - earlier).total_seconds()
    if secs < 0:
        return 0
    return int(secs // 86400)


def signed_whole_days(later, earlier):
    secs = (later - earlier).total_seconds()
    return int(secs // 86400)


# ---------------------------------------------------------------------------
# identity / common fields
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def base_row(with_common=True):
    ts = now()
    row = {"id": new_id()}
    row["created_at"] = ts
    if with_common:
        row["updated_at"] = ts
        row["version"] = 1
    row["_seq"] = store.next_row_seq()
    return row


def touch(row, bump=True):
    """A mutation: refresh updated_at and increment version by exactly 1."""
    if row is None:
        return row
    row["updated_at"] = now()
    if bump and "version" in row:
        row["version"] = row["version"] + 1
    return row


def order_key(row):
    """Default list ordering: created_at ascending, insertion order as tiebreak."""
    return (row.get("created_at") or CLOCK_START, row.get("_seq", 0))


def occurrence_key(row):
    """Renumbering order: occurred_at ascending, then created_at ascending."""
    return (row.get("occurred_at") or CLOCK_START,
            row.get("created_at") or CLOCK_START,
            row.get("_seq", 0))


def rows(table):
    return sorted(getattr(store, table).values(), key=order_key)
