"""In-memory store. Starts completely empty on every boot -- nothing is seeded."""
import itertools
import threading
import uuid

from util import iso, parse_iso
from config import CLOCK_EPOCH_ISO

_seq_counter = itertools.count(1)
lock = threading.RLock()

TABLE_NAMES = (
    "seasons",
    "episodes",
    "clusters",
    "live_events",
    "players",
    "accounts",
    "ledger",
    "offers",
    "disclosures",
    "purchases",
    "refunds",
    "balance_changes",
    "notices",
    "monitoring_runs",
)


class Store(object):
    def __init__(self):
        for name in TABLE_NAMES:
            setattr(self, name, {})
        self.clock = parse_iso(CLOCK_EPOCH_ISO)


db = Store()


def now():
    """The logical clock (PRD 2.4). Never falls back to wall-clock time."""
    return db.clock


def set_clock(dt):
    db.clock = dt


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)


def insert(table, data, common_fields=True):
    """Store a new record. `created_at`/`updated_at` are logical-clock stamps."""
    record = dict(data)
    record["id"] = new_id()
    stamp = iso(now())
    record["created_at"] = stamp
    if common_fields:
        record["updated_at"] = stamp
        record["version"] = 1
    record["_seq"] = next_seq()
    table[record["id"]] = record
    return record


def sort_key(record):
    """Default ordering: created_at ASC, insertion order as the stable tie-break."""
    return (record["created_at"], record["_seq"])


def ordered(records):
    return sorted(records, key=sort_key)


def serialize(record):
    out = {}
    for key, value in record.items():
        if key.startswith("_"):
            continue
        out[key] = _plain(value)
    return out


def _plain(value):
    from datetime import datetime

    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return dict((k, _plain(v)) for k, v in value.items())
    return value
