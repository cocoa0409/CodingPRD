"""In-memory data store.  Starts empty on every boot; nothing is ever seeded."""
import uuid
from decimal import Decimal

import clock

# Every collection starts empty.  No entity is ever preloaded.
protocols = {}
volunteers = {}
experts = {}
certifications = {}
campaigns = {}
sites = {}
observations = {}
photos = {}
votes = {}
equipment = {}
loans = {}
publications = {}
partners = {}
grants = {}
awards = {}

_seq = {"n": 0}

# rows mutated during the current request (id -> True); used so a row's version
# advances at most once per request no matter how many links touch it.
_touched = {"ids": set()}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def begin_request():
    _touched["ids"] = set()


def new_id():
    return str(uuid.uuid4())


def new_row(fields, common=True):
    """Build a record.  `fields` is an ordered dict of business fields."""
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = clock.now()
    if common:
        row["updated_at"] = clock.now()
        row["version"] = 1
    row["_seq"] = next_seq()
    # a freshly created row is already "current"; it must not be bumped again
    _touched["ids"].add(row["id"])
    return row


def touch(row):
    """Refresh updated_at and advance version, once per request per row."""
    if row is None:
        return
    if "version" not in row:
        return  # append-only ledger rows carry neither updated_at nor version
    if row["id"] in _touched["ids"]:
        row["updated_at"] = clock.now()
        return
    _touched["ids"].add(row["id"])
    row["updated_at"] = clock.now()
    row["version"] = row["version"] + 1


def order_key(row):
    return (row["created_at"], row["_seq"])


def all_rows(coll):
    return sorted(coll.values(), key=order_key)


def serialize(row):
    out = {}
    for k, v in row.items():
        if k.startswith("_"):
            continue
        out[k] = _val(v)
    return out


def _val(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    if hasattr(v, "tzinfo") and hasattr(v, "isoformat") and hasattr(v, "hour"):
        return clock.fmt(v)
    return v
