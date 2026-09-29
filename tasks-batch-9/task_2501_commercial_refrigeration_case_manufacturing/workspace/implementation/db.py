"""In-memory data store.

The store is empty on every boot: no entity is ever seeded, preloaded or
hardcoded here.  Everything is created by clients through the declared
endpoints.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

_seq_counter = itertools.count(1)

# PRD 2.4: before any operator sets it, the logical clock reads exactly this.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return fmt_dt(datetime.now(timezone.utc))


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.refrigerants = {}
        self.energy_standards = {}
        self.test_chambers = {}
        self.case_models = {}
        self.energy_tests = {}
        self.compliance_labels = {}
        self.store_plans = {}
        self.store_plan_lines = {}
        self.work_orders = {}
        self.shipments = {}
        self.install_crews = {}
        self.install_bookings = {}
        self.part_inventories = {}
        self.warranty_claims = {}
        self.clock = DEFAULT_CLOCK


db = Store()


def rows(collection):
    """All rows of a collection in created_at ascending order."""
    return sorted(collection.values(), key=lambda r: r["_seq"])


def new_row(common_fields=True):
    row = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
    }
    if common_fields:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def add_months(dt, months):
    """Advance an instant by whole calendar months, clamping the day."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = dt.day
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1


def day_start(dt):
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def occupied_days(start_dt, end_dt):
    """Whole UTC days d with start <= d < end (half-open interval)."""
    days = []
    cursor = day_start(start_dt)
    while cursor < end_dt:
        days.append(cursor.date())
        cursor = cursor + timedelta(days=1)
    return days
