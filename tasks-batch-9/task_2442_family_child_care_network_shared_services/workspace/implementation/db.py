"""In-memory data store.

Every collection starts EMPTY on every boot.  Nothing is seeded, preloaded or
hardcoded: tests build all state through the declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

# --- collections (id -> row dict) -------------------------------------------
providers = {}
agreements = {}
enrollments = {}
contracts = {}
claims = {}
remittances = {}
food_claims = {}
substitutes = {}
assignments = {}
visits = {}
reviews = {}
orders = {}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def now_iso():
    """Housekeeping timestamp: ISO 8601 UTC with exactly three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def make_row(**fields):
    """Create a row carrying the four common housekeeping properties."""
    ts = now_iso()
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = ts
    row["updated_at"] = ts
    row["version"] = 1
    row["_seq"] = next_seq()
    return row


def by_created_at(rows):
    """created_at ascending (insertion order, which is created_at order)."""
    return sorted(rows, key=lambda r: r["_seq"])
