"""In-memory data store, logical clock and row helpers.

The store starts completely empty on every boot: nothing is seeded, preloaded
or hardcoded.  Every entity is created by clients through the declared
endpoints.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.5 — the logical clock starts here when the process starts and no client
# has ever set it.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

TS_FMT = "%Y-%m-%dT%H:%M:%S"


class Store:
    """Every collection is a plain dict keyed by the row's id."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.split_schedules = {}
        self.consortiums = {}
        self.suppliers = {}
        self.advisors = {}
        self.agreements = {}
        self.credentials = {}
        self.clients = {}
        self.trust_entries = {}
        self.bookings = {}
        self.claims = {}
        self.runs = {}
        self.statements = {}
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


store = Store()


# --------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------

def now_clock():
    """The logical clock: the only time source for business decisions."""
    return store.clock


def fmt_ts(value):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if value is None:
        return None
    if not isinstance(value, datetime):
        return value
    dt = value.astimezone(timezone.utc)
    return "%s.%03dZ" % (dt.strftime(TS_FMT), dt.microsecond // 1000)


def wall_now_iso():
    dt = datetime.now(timezone.utc)
    return "%s.%03dZ" % (dt.strftime(TS_FMT), dt.microsecond // 1000)


def parse_iso8601(raw):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith("z") or text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def date_of(dt):
    return dt.astimezone(timezone.utc).date()


def year_window(dt):
    """[first instant of the calendar year, first instant of the next year)."""
    y = dt.astimezone(timezone.utc).year
    return (datetime(y, 1, 1, tzinfo=timezone.utc),
            datetime(y + 1, 1, 1, tzinfo=timezone.utc))


def month_window(period_month):
    """[first instant of period_month, first instant of the following month)."""
    year = int(period_month[:4])
    month = int(period_month[5:7])
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def add_days(dt_date, days):
    return dt_date + timedelta(days=days)


# --------------------------------------------------------------------------
# row helpers
# --------------------------------------------------------------------------

def new_row(fields, versioned=True):
    """Mint a row with the common properties from PRD 2.4."""
    row = {
        "id": str(uuid.uuid4()),
        "created_at": store.clock,
        "_seq": store.next_seq(),
    }
    if versioned:
        row["updated_at"] = store.clock
        row["version"] = 1
    row.update(fields)
    return row


def touch(row):
    """A mutation the server applies: refresh updated_at, bump version by 1."""
    row["updated_at"] = store.clock
    row["version"] = row.get("version", 0) + 1


def ordered(rows):
    """created_at ascending; insertion sequence breaks ties deterministically."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def serialize(row):
    out = {}
    for key, value in row.items():
        if key == "_seq":
            continue
        if isinstance(value, datetime):
            out[key] = fmt_ts(value)
        else:
            out[key] = value
    return out
