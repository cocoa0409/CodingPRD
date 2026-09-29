"""In-memory store, logical UTC clock, and per-request mutation tracking.

The store starts EMPTY on every boot: nothing is seeded, preloaded or
hardcoded.  Every row is created by a client through the declared API surface.
"""

import copy
import itertools
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

LOCK = threading.RLock()

TABLES = (
    "theatres",
    "productions",
    "theatre_engagements",
    "budget_lines",
    "operating_budgets",
    "offering_documents",
    "investors",
    "subscriptions",
    "investor_accounts",
    "royalty_participants",
    "weekly_wraps",
    "royalty_allocations",
    "subsidiary_rights_income",
    "investor_distributions",
    "closing_notices",
)

store = {name: {} for name in TABLES}

_seq_counter = itertools.count(1)

# PRD 2.4: the logical clock reads exactly 2026-08-01T00:00:00Z at startup and
# never falls back to real wall-clock time.
CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


# ---------------------------------------------------------------- timestamps
def iso_ts(dt=None):
    dt = dt or datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def logical_now():
    return CLOCK["now"]


def logical_date():
    return CLOCK["now"].date()


def new_id():
    return str(uuid.uuid4())


# ------------------------------------------------------------------ rounding
def rhu(value, places=0):
    """round_half_up to `places` decimals; returns Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exp = Decimal(1).scaleb(-places)
    return value.quantize(exp, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def div(num, den):
    return Decimal(num) / Decimal(den)


def ceil_div(num, den):
    return int((Decimal(num) / Decimal(den)).to_integral_value(rounding=ROUND_CEILING))


ZERO4 = Decimal("0.0000")
ZERO6 = Decimal("0.000000")
ONE4 = Decimal("1.0000")
ONE6 = Decimal("1.000000")


# ---------------------------------------------------------------- row helpers
def insert(table, fields, versioned=True):
    ts = iso_ts()
    row = {"id": new_id(), "created_at": ts}
    if versioned:
        row["updated_at"] = ts
        row["version"] = 1
    row.update(fields)
    row["_seq"] = next(_seq_counter)
    store[table][row["id"]] = row
    return row


def get(table, row_id):
    if not isinstance(row_id, str):
        return None
    return store[table].get(row_id)


def all_rows(table):
    return sorted(store[table].values(), key=lambda r: r["_seq"])


def _snap(row):
    return copy.deepcopy({k: v for k, v in row.items()
                          if k not in ("updated_at", "version")})


class RequestContext:
    """Collects rows written during a request.

    PRD 2.6: a successful request increments the version of each row it writes
    by exactly 1, no matter how many cascade hops touch the row.  Rows created
    during the request keep version 1.
    """

    def __init__(self):
        self._rows = {}
        self._snaps = {}
        self._forced = set()
        self._created = set()

    def watch(self, row):
        key = id(row)
        if key not in self._rows:
            self._rows[key] = row
            self._snaps[key] = _snap(row)
        return row

    def force(self, row):
        self.watch(row)
        self._forced.add(id(row))
        return row

    def created(self, row):
        key = id(row)
        self._rows[key] = row
        self._snaps[key] = _snap(row)
        self._created.add(key)
        return row

    def commit(self):
        ts = iso_ts()
        for key, row in self._rows.items():
            if key in self._created:
                continue
            if "version" not in row:
                continue
            if key in self._forced or _snap(row) != self._snaps[key]:
                row["updated_at"] = ts
                row["version"] = row["version"] + 1


# ---------------------------------------------------------------- serializing
def _plain(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def serialize(row):
    if row is None:
        return None
    return {k: _plain(v) for k, v in row.items() if not k.startswith("_")}


def serialize_all(rows):
    return [serialize(r) for r in rows]


# --------------------------------------------------------------------- dates
def parse_iso_date(text):
    """Strict ISO 8601 calendar date; returns date or None."""
    if not isinstance(text, str) or len(text) != 10:
        return None
    if text[4] != "-" or text[7] != "-":
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def days_between(a, b):
    return (b - a).days


def add_days(d, n):
    return d + timedelta(days=n)
