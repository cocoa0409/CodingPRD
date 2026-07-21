"""In-memory data store and record helpers.

The store starts EMPTY on every boot. Nothing is seeded or preloaded.
"""
import uuid
import itertools
from datetime import datetime, timezone

VERSION_INITIAL = 1

# One dict per collection, keyed by id.
brokers = {}
sellers = {}
buyers = {}
listings = {}
cims = {}
ndas = {}
documents = {}
meetings = {}
deals = {}
lois = {}
loans = {}
escrows = {}

_seq_counter = itertools.count(1)


def now_iso():
    # ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def gen_id():
    return str(uuid.uuid4())


def new_record(extra):
    ts = now_iso()
    rec = {
        "id": gen_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": VERSION_INITIAL,
        "_seq": next(_seq_counter),
    }
    rec.update(extra)
    return rec


def touch(rec):
    """Register a mutation: bump version + refresh updated_at."""
    rec["version"] = rec.get("version", VERSION_INITIAL) + 1
    rec["updated_at"] = now_iso()
