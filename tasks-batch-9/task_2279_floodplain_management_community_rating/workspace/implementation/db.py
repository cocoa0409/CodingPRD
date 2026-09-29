"""In-memory data store, logical clock, and identity/timestamp helpers.

The store is EMPTY on every boot.  No entity is ever seeded, preloaded or
hardcoded at startup; every row is created through the declared API surface.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# PRD 2.5 — the logical clock starts at exactly this instant on every boot.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.communities = {}
        self.firm_panels = {}
        self.properties = {}
        self.structures = {}
        self.permits = {}
        self.certificates = {}
        self.records = {}
        self.cases = {}
        self.inspections = {}
        self.violations = {}
        self.orders = {}
        self.loss_areas = {}
        self.standards = {}
        self.cycles = {}
        self.sweeps = []
        self.clock = CLOCK_START
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    return db.clock


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def iso_now():
    return iso(now())


def parse_dt(value):
    """Parse an ISO 8601 instant into an aware UTC datetime.  Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("blank")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_dt(value):
    """Coerce a stored timestamp (string or datetime) back to a datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    return parse_dt(value)


def plus_days(dt, days):
    return to_dt(dt) + timedelta(days=days)


def shift_years(dt, years):
    """Calendar-year arithmetic; 29 February clamps to 28 February."""
    dt = to_dt(dt)
    target_year = dt.year + years
    try:
        return dt.replace(year=target_year)
    except ValueError:
        return dt.replace(year=target_year, month=2, day=28)


def base_fields(versioned=True):
    created = iso_now()
    row = {"id": new_id(), "created_at": created, "_seq": db.next_seq()}
    if versioned:
        row["updated_at"] = created
        row["version"] = 1
    return row


def touch(row):
    row["updated_at"] = iso_now()
    row["version"] = row.get("version", 1) + 1


def sort_rows(rows):
    """Ascending created_at; insertion sequence breaks ties deterministically."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def sort_rows_desc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]), reverse=True)


def public(row):
    """Strip internal fields and make the payload JSON-serialisable."""
    if row is None:
        return None
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        out[key] = jsonable(value)
    return out


def jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    return value
