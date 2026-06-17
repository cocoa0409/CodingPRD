"""In-memory data store. Wiped on every fresh boot — no seeding, no persistence.

Each entity kind is a dict keyed by id. Records are plain dicts. A monotonic
counter on creation preserves insertion order for created_at tie-breaks where
the spec leans on "earlier-inserted wins" (e.g. deposit_waterfall §3.10).
"""
import threading
import uuid

from response import now_iso

# One lock to make multi-step mutations atomic enough for the test harness.
LOCK = threading.RLock()

# Per-kind dicts: id -> record
clients = {}
projects = {}
rooms = {}
moodboards = {}
ffe_items = {}
selections = {}
vendors = {}
orders = {}
order_lines = {}
revisions = {}
punch_items = {}
time_entries = {}
payments = {}

_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    # server-minted UUID with no type prefix (PRD §2.4)
    return str(uuid.uuid4())


def new_common():
    """id/created_at/updated_at/version quartet (PRD §2.4)."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def now_iso_for_line():
    """created_at for an immutable OrderLine join row (no updated_at/version)."""
    return now_iso()


def touch(record):
    """A mutation bumps updated_at and increments version (PRD §2.4)."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
