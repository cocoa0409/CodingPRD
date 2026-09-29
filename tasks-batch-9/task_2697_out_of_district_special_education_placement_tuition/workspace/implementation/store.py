"""In-memory data store, logical clock and row helpers.

The store starts completely empty on every boot. Nothing is ever seeded,
preloaded or hardcoded — every row is created by a declared endpoint.
"""
import uuid
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal

from flask import g

# The logical clock starts at exactly this instant on every boot.
CLOCK_ORIGIN = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# Collection keys -> human kind name used for scope resolution.
COLLECTIONS = (
    "students",
    "schools",
    "rate_schedules",
    "decisions",
    "placements",
    "addenda",
    "routes",
    "assignments",
    "attendance",
    "invoices",
    "reimbursements",
    "progress",
    "plans",
    "funding",
    "accounts",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_ORIGIN
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# --------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------

def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now():
    return db.clock


def now_iso():
    return iso(db.clock)


def clock_date():
    return db.clock.date()


def parse_date(value):
    """Strict calendar date parse; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except (ValueError, TypeError):
        return None


def parse_datetime(value):
    """Parse an ISO 8601 UTC instant. Returns None when unparseable."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        # bare date is also acceptable as an instant at midnight UTC
        d = parse_date(value)
        if d is None:
            return None
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def day_span(start, end):
    """Inclusive-day count between two dates."""
    return (end - start).days + 1


def add_days(d, n):
    return d + timedelta(days=n)


# --------------------------------------------------------------------------
# row helpers
# --------------------------------------------------------------------------

def new_row(kind, fields):
    stamp = now_iso()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    row.update(fields)
    row["_kind"] = kind
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """Refresh updated_at and advance version — at most once per request.

    PRD 2.4: one client request advances a given row's counter by exactly one
    even when a cascade writes that row through several links.
    """
    if row is None:
        return
    try:
        seen = g._touched
    except (AttributeError, RuntimeError):
        seen = None
    if seen is None:
        try:
            seen = set()
            g._touched = seen
        except RuntimeError:
            seen = None
    key = id(row)
    if seen is not None:
        if key in seen:
            return
        seen.add(key)
    row["updated_at"] = now_iso()
    row["version"] = row["version"] + 1


def reset_touch():
    """Start a fresh touch epoch (used by the multi-event clock sweep)."""
    try:
        g._touched = set()
    except RuntimeError:
        pass


def ordered(rows):
    """Ascending created_at with a stable insertion-order tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def to_json(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [to_json(v) for v in value]
    if isinstance(value, tuple):
        return [to_json(v) for v in value]
    if isinstance(value, dict):
        return dict((k, to_json(v)) for k, v in value.items())
    return value


def public(row):
    return dict((k, to_json(v)) for k, v in row.items() if not k.startswith("_"))


def public_list(rows):
    return [public(r) for r in rows]
