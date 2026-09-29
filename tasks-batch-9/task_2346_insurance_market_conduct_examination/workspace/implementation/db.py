"""In-memory store, logical clock and record helpers.

The store starts completely empty on every boot: nothing is seeded, preloaded or
hardcoded. Tests build every precondition through the declared API surface.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

# PRD §2.4 — before any client sets it the logical clock reads exactly this.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.insurers = {}
        self.cycles = {}
        self.analysis_scores = {}
        self.examinations = {}
        self.scope_areas = {}
        self.data_calls = {}
        self.file_samples = {}
        self.fieldwork_activities = {}
        self.criticisms = {}
        self.company_responses = {}
        self.plans = {}
        self.consent_orders = {}
        self.collaborations = {}
        self.clock = CLOCK_EPOCH
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


# ---------------------------------------------------------------- logical clock
def now_dt():
    return db.clock


def set_clock(dt):
    db.clock = dt


def iso(dt):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso(db.clock)


def today_str():
    return db.clock.strftime("%Y-%m-%d")


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def date_str(d):
    return d.strftime("%Y-%m-%d")


def day_diff(later, earlier):
    """Whole-day difference between two YYYY-MM-DD strings (later - earlier)."""
    return (parse_date(later) - parse_date(earlier)).days


def add_days(date_string, days):
    return date_str(parse_date(date_string) + timedelta(days=days))


def add_months(date_string, months):
    """Calendar-month arithmetic, clamped to the last day of the target month."""
    d = parse_date(date_string)
    total = (d.year * 12 + (d.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    day = d.day
    while True:
        try:
            return date_str(d.replace(year=year, month=month, day=day))
        except ValueError:
            day -= 1


# --------------------------------------------------------------------- records
def new_id():
    return str(uuid.uuid4())


def new_record(fields, versioned=True):
    """Mint a record with its audit stamps (PRD §2.4)."""
    record = {"id": new_id(), "created_at": now_iso()}
    if versioned:
        record["updated_at"] = now_iso()
        record["version"] = 1
    record.update(fields)
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """A mutation: refresh updated_at and increment version by exactly 1."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record


def by_creation(rows):
    """List ordering: created_at ascending, insertion order as the tie-break.

    A record's id is never consulted as a tie-break anywhere in this service.
    """
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
