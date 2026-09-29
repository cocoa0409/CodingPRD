"""In-memory data store, logical clock and shared numeric helpers.

Storage is process-local Python dicts only. The store starts EMPTY on every boot:
nothing is seeded, preloaded or hardcoded — every entity is built by the caller
through the declared endpoints.
"""

import uuid
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import g

# --------------------------------------------------------------------------- #
# numeric helpers - money is Decimal everywhere, never float
# --------------------------------------------------------------------------- #

ZERO = Decimal("0.00")


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def q2(value):
    return D(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q4(value):
    return D(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def q0(value):
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------- #
# logical clock (PRD 2.7) - starts at exactly 2026-08-01T00:00:00Z, never falls
# back to wall-clock time
# --------------------------------------------------------------------------- #

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.employers = {}
        self.coordinators = {}
        self.campaigns = {}
        self.pledges = {}
        self.designations = {}
        self.agencies = {}
        self.reviews = {}
        self.cycles = {}
        self.requests = {}
        self.panelists = {}
        self.assignments = {}
        self.scores = {}
        self.reports = {}
        self.seq = 0
        self.clock = DEFAULT_CLOCK


db = Store()


def now():
    return db.clock


def today():
    return db.clock.date()


def set_clock(dt):
    db.clock = dt


def iso(dt):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso(db.clock)


def date_of(ts):
    """Date part of a stored ISO timestamp string."""
    if ts is None:
        return None
    return date(int(ts[0:4]), int(ts[5:7]), int(ts[8:10]))


def plus_days(d, n):
    return d + timedelta(days=n)


# --------------------------------------------------------------------------- #
# identity / audit helpers (PRD 2.4)
# --------------------------------------------------------------------------- #


def next_seq():
    db.seq += 1
    return db.seq


def base_entity():
    ts = now_iso()
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(kind, entity):
    """Bump version by exactly one and refresh updated_at.

    One business action may re-derive several fields of the same row (PRD 2.4:
    confirming a pledge re-derives four campaign totals yet the campaign row is
    one mutation), so repeated touches of the same row inside a single request
    collapse into a single version increment.
    """
    if entity is None:
        return entity
    key = (kind, entity["id"])
    touched = getattr(g, "_touched", None)
    if touched is None:
        touched = set()
        g._touched = touched
    if key in touched:
        return entity
    touched.add(key)
    entity["version"] = entity["version"] + 1
    entity["updated_at"] = now_iso()
    return entity


def sort_created_asc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def sort_created_desc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]), reverse=True)
