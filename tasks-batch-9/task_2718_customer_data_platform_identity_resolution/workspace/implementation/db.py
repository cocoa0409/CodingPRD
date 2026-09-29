"""In-memory data store, logical clock and shared entity helpers.

The store is always empty on boot -- nothing is ever seeded here.
"""

import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

from errors import ApiError

# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------

COLLECTIONS = (
    "source_systems",
    "ingest_batches",
    "profiles",
    "households",
    "match_rules",
    "identity_links",
    "consent_records",
    "suppression_entries",
    "segments",
    "destinations",
    "activations",
    "deletion_requests",
    "vendor_deletion_tasks",
)

store = {name: {} for name in COLLECTIONS}

_seq_counter = itertools.count(1)

# The logical clock starts at exactly this instant on every boot.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_EPOCH}


def now():
    """Current logical instant. Never falls back to the wall clock."""
    return _clock["now"]


def set_now(value):
    _clock["now"] = value


def next_seq():
    return next(_seq_counter)


# --------------------------------------------------------------------------
# Timestamps
# --------------------------------------------------------------------------

_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def iso(dt):
    """Serialize an aware datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_ts(value):
    """Parse an ISO 8601 timestamp string. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _TS_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, off = m.groups()
    try:
        micro = 0
        if frac:
            digits = (frac[1:] + "000000")[:6]
            micro = int(digits)
        base = datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second), micro,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    if off and off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        off = off[1:].replace(":", "")
        delta = timedelta(hours=int(off[:2]), minutes=int(off[2:4]))
        base = base - sign * delta
    return base


def date_str(dt):
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


# --------------------------------------------------------------------------
# Entities
# --------------------------------------------------------------------------

def new_entity(collection, **fields):
    stamp = now()
    entity = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next_seq(),
    }
    entity.update(fields)
    store[collection][entity["id"]] = entity
    return entity


def touch(entity):
    """Record a mutation: bump version by exactly 1 and restamp updated_at."""
    entity["version"] += 1
    entity["updated_at"] = now()
    return entity


def all_of(collection):
    return list(store[collection].values())


def by_seq(entities):
    """created_at ascending, insertion order as the stable tie-break."""
    return sorted(entities, key=lambda e: (e["created_at"], e["_seq"]))


def get_or_404(collection, entity_id, error_id):
    entity = store[collection].get(entity_id)
    if entity is None:
        raise ApiError(error_id)
    return entity


# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------

def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total
