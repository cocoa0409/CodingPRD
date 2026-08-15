"""In-memory data store. Module-level dicts; empty at every process boot."""

import threading
import uuid
from datetime import datetime, timedelta, timezone

lock = threading.RLock()

vessels = {}
certificates = {}
jobs = {}
slots = {}
rows = {}
assignments = {}
work_orders = {}
labor_entries = {}
parts = {}
events = {}
holds = {}
ledger = {}

_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())


_last_ts = [None]


def now_iso():
    """Wall-clock UTC timestamp with 3 fractional digits, strictly monotonic."""
    n = datetime.now(timezone.utc)
    if _last_ts[0] is not None and n <= _last_ts[0]:
        n = _last_ts[0] + timedelta(milliseconds=1)
    _last_ts[0] = n
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def pub(rec):
    """Public view of a record: strip internal keys (prefixed with '_')."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def touch(rec):
    """Bump optimistic-concurrency fields after a mutation."""
    rec["version"] += 1
    rec["updated_at"] = now_iso()
