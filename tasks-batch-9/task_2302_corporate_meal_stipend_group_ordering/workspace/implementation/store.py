"""In-memory data store.

The store starts completely EMPTY on every boot: nothing is seeded, preloaded or
hardcoded. Every entity is created by an explicit API call.
"""

import itertools
import uuid
from datetime import datetime, timezone

# PRD §2.5 — the logical clock's value before it is ever set.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.meal_programs = {}
        self.employee_groups = {}
        self.budget_rules = {}
        self.employees = {}
        self.benefit_periods = {}
        self.restaurants = {}
        self.delivery_locations = {}
        self.group_orders = {}
        self.orders = {}
        self.credit_claims = {}
        self.refund_entries = {}
        self.imputed_records = {}
        self.expense_exports = {}
        self.now = DEFAULT_CLOCK
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


db = Store()


# --------------------------------------------------------------------------
# timestamps
# --------------------------------------------------------------------------
def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_str():
    return fmt_dt(db.now)


def new_id():
    return str(uuid.uuid4())


def base_row():
    """Common fields: id, created_at, updated_at, version (PRD §2.4)."""
    stamp = now_str()
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(row):
    """Any mutation refreshes updated_at and increments version by exactly 1."""
    row["updated_at"] = now_str()
    row["version"] = row.get("version", 1) + 1
    return row


def public(row, exclude=()):
    return {k: v for k, v in row.items()
            if not k.startswith("_") and k not in exclude}


def sort_rows(rows):
    """Default list ordering: created_at ascending (stable by insertion)."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))
