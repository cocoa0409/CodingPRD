"""In-memory store, logical clock and record helpers.

The store starts EMPTY on every boot: no entity is seeded or preloaded.
"""
import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.5: the logical clock reads exactly this at startup and never falls
# back to wall-clock time.
CLOCK_DEFAULT = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "organizations",
    "campaigns",
    "events",
    "teams",
    "participants",
    "registrations",
    "donors",
    "donations",
    "match_pools",
    "incentive_tiers",
    "incentive_awards",
    "receipts",
    "payouts",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_DEFAULT
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


store = Store()


# --------------------------------------------------------------------- time
def now():
    return store.clock


def set_clock(dt):
    store.clock = dt


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso(now())


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
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


def dt_of(value):
    """Parse a stored ISO string field back into a datetime (None-safe)."""
    if not value:
        return None
    return parse_iso(value)


def days(n):
    return timedelta(days=n)


def minutes(n):
    return timedelta(minutes=n)


# ------------------------------------------------------------------ records
def new_id():
    return str(uuid.uuid4())


def new_record(**fields):
    stamp = now_iso()
    rec = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": store.next_seq(),
    }
    rec.update(fields)
    return rec


def touch(rec):
    """PRD 2.11: a touched resource gets a fresh updated_at and version+1."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
    return rec


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def ordered(records):
    """PRD 2.3: collections are ordered by created_at ascending."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
