"""In-memory data store, logical clock, id minting and common-field helpers.

The store is empty on every boot. Nothing in this module — or anywhere else in
the implementation — seeds, preloads or hardcodes any entity. Every row is
created by an API caller.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from constants import CLOCK_DEFAULT_ISO

TWO_PLACES = Decimal("0.01")


def _parse_default_clock():
    return datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    """Every collection is a plain dict keyed by the row's uuid."""

    def __init__(self):
        self.operators = {}
        self.mine_sites = {}
        self.inspector_profiles = {}
        self.permits = {}
        self.estimates = {}
        self.instruments = {}
        self.release_apps = {}
        self.inspections = {}
        self.notices = {}
        self.revisions = {}
        self.proceedings = {}
        self.clock = _parse_default_clock()
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# --------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# --------------------------------------------------------------------------
def now():
    return db.clock


def set_clock(value):
    db.clock = value


# --------------------------------------------------------------------------
# Decimal helpers (PRD 2.6 — two decimals, round half up, everywhere)
# --------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def money(value):
    return D(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def money_floor0(value):
    result = money(value)
    return result if result > 0 else Decimal("0.00")


ZERO = Decimal("0.00")


# --------------------------------------------------------------------------
# Common fields (PRD 2.4)
# --------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def base_row():
    stamp = now()
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(row):
    """Refresh updated_at and increment version by exactly 1."""
    row["updated_at"] = now()
    row["version"] += 1


def fmt_ts(value):
    """ISO 8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    dt = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def days(count):
    return timedelta(days=count)


def sort_rows(rows):
    """Default list ordering: created_at ascending (insertion order breaks ties
    because the logical clock frequently stamps identical instants)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
