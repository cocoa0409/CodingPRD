"""In-memory data store and the server-held logical clock.

The store always starts empty: no entity is ever seeded at boot.  Every record
any test needs is built through the declared API surface.
"""
import random
import string
import uuid
from datetime import datetime, timezone

from flask import g

UTC = timezone.utc
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

STORE_NAMES = (
    "providers",
    "agents",
    "policies",
    "accounts",
    "content_items",
    "rights_holders",
    "notices",
    "claims",
    "counter_notices",
    "strikes",
    "termination_cases",
    "misrep_cases",
    "reference_files",
    "batches",
    "audits",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in STORE_NAMES:
            setattr(self, name, {})
        self.clock = CLOCK_EPOCH


db = Store()


def now():
    return db.clock


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%s.%03dZ" % (dt.strftime("%Y-%m-%dT%H:%M:%S"), dt.microsecond // 1000)


def parse_instant(value):
    """Parse an ISO-8601 instant; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


# --------------------------------------------------------------------------
# record helpers
# --------------------------------------------------------------------------
def create(store, fields):
    """Create a record carrying the common property set (id/created_at/updated_at/version)."""
    stamp = db.clock
    record = {"id": new_id()}
    record.update(fields)
    record["created_at"] = stamp
    record["updated_at"] = stamp
    record["version"] = 1
    store[record["id"]] = record
    return record


def create_immutable(store, fields):
    """Create an evidentiary record carrying only id and created_at."""
    record = {"id": new_id()}
    record.update(fields)
    record["created_at"] = db.clock
    store[record["id"]] = record
    return record


def touch(record):
    """Mark a record as mutated by the current request.

    A record mutated by a request has its updated_at refreshed and its version
    incremented by exactly 1 for that request, no matter how many individual
    fields the request rewrote.
    """
    if record is None:
        return record
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = {}
        g.touched = touched
    touched[id(record)] = record
    return record


def update(record, **fields):
    """Write fields onto a record, marking it mutated when a value actually changed."""
    changed = False
    for key, value in fields.items():
        if key not in record or record[key] != value:
            record[key] = value
            changed = True
    if changed:
        touch(record)
    return record


def commit():
    touched = getattr(g, "touched", None)
    if not touched:
        return
    for record in touched.values():
        if "version" in record:
            record["version"] = record["version"] + 1
            record["updated_at"] = db.clock
    g.touched = {}


def rows(store):
    """All records of a store in insertion order."""
    return list(store.values())
