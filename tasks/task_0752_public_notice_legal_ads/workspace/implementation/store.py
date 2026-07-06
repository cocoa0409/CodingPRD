"""In-memory data store, logical clock, and id/timestamp helpers.

All state lives in module-level dicts on a single Store instance. Every process
boot starts empty; no entity is ever seeded. `start.sh` re-invocation wipes state
simply by starting a fresh process.
"""
import uuid
import math
from datetime import datetime, date, time, timezone, timedelta

UTC = timezone.utc

# Logical-clock startup default (PRD 2.7).
DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.newspapers = {}
        self.accounts = {}
        self.statutory = {}
        self.notices = {}
        self.insertions = {}
        self.proofs = {}
        self.affidavits = {}
        self.invoices = {}
        self.line_items = {}
        self.payments = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0


db = Store()


# --------------------------------------------------------------------------
# ids / sequence
# --------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def next_seq():
    db._seq += 1
    return db._seq


# --------------------------------------------------------------------------
# timestamps
# --------------------------------------------------------------------------
def real_now():
    return datetime.now(UTC)


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_dt(s):
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def parse_date(s):
    s = s.strip()
    if "T" in s or " " in s:
        return parse_dt(s).date()
    return date.fromisoformat(s)


def date_to_dt(d):
    return datetime.combine(d, time(0, 0, 0), tzinfo=UTC)


# --------------------------------------------------------------------------
# entity construction / mutation
# --------------------------------------------------------------------------
def make_entity(fields, light=False):
    """Create an entity dict with id + audit fields.

    light=True yields an immutable ledger record (InvoiceLineItem / Payment):
    only id and created_at, no updated_at and no version (PRD 2.4).
    """
    e = dict(fields)
    e["id"] = new_id()
    e["_seq"] = next_seq()
    ts = fmt_ts(real_now())
    e["created_at"] = ts
    if not light:
        e["updated_at"] = ts
        e["version"] = 1
    return e


def touch(e):
    """Register a mutation: bump version and refresh updated_at (PRD 2.4)."""
    e["updated_at"] = fmt_ts(real_now())
    e["version"] = e.get("version", 1) + 1


def ceil_div(n, d):
    return math.ceil(n / d)
