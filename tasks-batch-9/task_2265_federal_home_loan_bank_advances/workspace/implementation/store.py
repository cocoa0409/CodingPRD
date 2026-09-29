"""In-memory store, logical clock, id minting and datetime helpers.

The store starts completely empty on every boot: no entity is ever seeded.
"""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

import config

# ---------------------------------------------------------------- datetimes --


def parse_dt(value):
    """Parse an ISO-8601 instant (or bare date) into an aware UTC datetime.

    Raises ValueError when the value cannot be parsed.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def whole_days_between(start, end):
    """Whole days from ``start`` to ``end`` (floored, may be negative)."""
    return (end - start).days


def date_days_between(start, end):
    """Whole calendar days from ``start``'s date to ``end``'s date."""
    return (end.date() - start.date()).days


# -------------------------------------------------------------------- store --


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.members = {}
        self.subscriptions = {}
        self.assets = {}
        self.receipts = {}
        self.reviews = {}
        self.findings = {}
        self.products = {}
        self.advances = {}
        self.prepayments = {}
        self.allocations = {}
        self.clock = parse_dt(config.DEFAULT_CLOCK_ISO)
        self.market_rate_bps = config.MARKET_RATE_DEFAULT_BPS
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock

    def now_iso(self):
        return fmt_dt(self.clock)


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# ------------------------------------------------------- entity bookkeeping --


def new_entity(kind):
    """Create the common system-managed field block for a new resource."""
    stamp = db.now_iso()
    return {
        "_kind": kind,
        "_seq": db.next_seq(),
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }


def finalize(entity, tail_keys=("created_at", "updated_at", "version")):
    """Move the audit tail to the end of the insertion order for readability."""
    tail = {k: entity.pop(k) for k in tail_keys if k in entity}
    entity.update(tail)
    return entity


def _touched_set():
    if not hasattr(g, "_touched_entities"):
        g._touched_entities = set()
    return g._touched_entities


def touch(entity):
    """Bump ``version``/``updated_at`` at most once per request per entity."""
    key = (entity.get("_kind"), entity.get("id"))
    seen = _touched_set()
    if key in seen:
        return entity
    seen.add(key)
    entity["updated_at"] = db.now_iso()
    entity["version"] = entity.get("version", 1) + 1
    return entity


def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def sort_records(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
