"""In-memory data store, logical clock and record helpers.

Storage is process-local Python dicts only: nothing is persisted and nothing is
seeded.  Every entity is created through the declared API surface.
"""

import itertools
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# The logical clock's default instant.  Nothing in this system ever reads the
# host machine's wall clock.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

COLLECTIONS = (
    "feed_sources",
    "residents",
    "service_addresses",
    "utility_providers",
    "territories",
    "moves",
    "verifications",
    "orders",
    "handoffs",
    "filings",
    "partners",
    "placements",
    "consents",
    "ledger",
)


def parse_ts(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime, or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date, or None."""
    if not isinstance(value, str) or len(value) != 10:
        return None
    if value[4] != "-" or value[7] != "-":
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def iso(dt):
    """Render an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self._seq = itertools.count(1)
        self.clock = parse_ts(DEFAULT_CLOCK_ISO)
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        return next(self._seq)


db = Store()


def now():
    """The logical-clock instant as an aware datetime."""
    return db.clock


def now_iso():
    return iso(db.clock)


def clock_date():
    return db.clock.date()


def new_id():
    return str(uuid.uuid4())


def base_record(versioned=True):
    stamp = now_iso()
    rec = {"id": new_id(), "created_at": stamp, "_seq": db.next_seq()}
    if versioned:
        rec["updated_at"] = stamp
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and increment version for any mutated row."""
    if "version" in rec:
        rec["version"] = rec["version"] + 1
    if "updated_at" in rec:
        rec["updated_at"] = now_iso()
    return rec


def order_key(rec):
    """Deterministic created_at ascending ordering (insertion order breaks ties)."""
    return (rec.get("created_at") or "", rec.get("_seq") or 0)


def created_before(candidate, reference):
    """True when candidate's row existed before reference's row was written."""
    return order_key(candidate) < order_key(reference)


def public(rec):
    """Strip internal bookkeeping keys from a record for serialization."""
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def round_money(value, places=0):
    """Decimal HALF_UP rounding to the requested number of decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exp = Decimal(1).scaleb(-places)
    return value.quantize(exp, rounding=ROUND_HALF_UP)


def round_int(value):
    return int(round_money(value, 0))


def add_days(d, days):
    return d + timedelta(days=days)
