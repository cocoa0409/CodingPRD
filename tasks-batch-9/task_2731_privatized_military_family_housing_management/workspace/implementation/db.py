"""In-memory data store, logical clock and row helpers.

The store starts completely empty on every boot: nothing is seeded, preloaded
or hardcoded.  All state is produced by API calls.
"""

import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone

# PRD 2.4: the logical clock starts at exactly this instant on every boot.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "installations",
    "bah_rates",
    "housing_units",
    "service_members",
    "dependents",
    "applications",
    "leases",
    "inspections",
    "work_orders",
    "hazard_cases",
    "lodgings",
    "disputes",
    "transactions",
    "accounts",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_DEFAULT
        self.seq = 0
        self.metrics_runs = set()
        self.bumped = set()


db = Store()


# ---------------------------------------------------------------- clock / time

def now():
    return db.clock


def set_clock(dt):
    db.clock = dt


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return iso(db.clock)


def today():
    return db.clock.astimezone(timezone.utc).date()


def parse_dt(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("not a datetime")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str) or len(value.strip()) != 10:
        raise ValueError("not a date")
    return date.fromisoformat(value.strip())


def fmt_date(d):
    return d.isoformat()


def parse_period(value):
    """'YYYY-MM' -> (year, month)."""
    if not isinstance(value, str) or len(value) != 7 or value[4] != "-":
        raise ValueError("not a period")
    year = int(value[0:4])
    month = int(value[5:7])
    if month < 1 or month > 12:
        raise ValueError("not a period")
    return year, month


def period_of(d):
    return "%04d-%02d" % (d.year, d.month)


def days_in_month(year, month):
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    return (nxt - date(year, month, 1)).days


def month_bounds(period):
    year, month = parse_period(period)
    first = date(year, month, 1)
    last = date(year, month, days_in_month(year, month))
    return first, last


# ------------------------------------------------------------------ row basics

def new_id():
    return str(uuid.uuid4())


_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def next_seq():
    db.seq += 1
    return db.seq


def base_row(common=True):
    row = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
    }
    if common:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def begin_request():
    """A row mutated several times inside one request still advances by exactly 1."""
    db.bumped = set()


def bump(row):
    key = row.get("id")
    if key in db.bumped:
        row["updated_at"] = now_iso()
        return
    db.bumped.add(key)
    row["updated_at"] = now_iso()
    row["version"] = int(row.get("version", 1)) + 1


def public(row):
    if row is None:
        return None
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        if isinstance(value, list):
            out[key] = [public(v) if isinstance(v, dict) else v for v in value]
        else:
            out[key] = value
    return out


def sort_rows(rows):
    """Default list order: created_at ascending (insertion order tie-break)."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def collection(name):
    return getattr(db, name)


def all_sorted(name):
    return sort_rows(list(getattr(db, name).values()))


__all__ = [
    "db", "Store", "CLOCK_DEFAULT", "now", "set_clock", "iso", "now_iso",
    "today", "parse_dt", "parse_date", "fmt_date", "parse_period", "period_of",
    "days_in_month", "month_bounds", "new_id", "request_id", "next_seq",
    "base_row", "bump", "begin_request", "public", "sort_rows", "collection",
    "all_sorted",
    "timedelta", "date", "datetime", "timezone",
]
