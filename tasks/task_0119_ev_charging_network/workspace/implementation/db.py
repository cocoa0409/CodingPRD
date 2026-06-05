"""In-memory data store.

ALL state lives in module-level dicts keyed by id. Nothing is seeded at
startup; every entity is created via the declared API surface. A fresh process
(per-test-server restart) starts completely empty.
"""
import uuid

from clock import now_iso

# Entity collections keyed by id.
sites = {}
stalls = {}
drivers = {}
emsps = {}
tariffs = {}
reservations = {}
sessions = {}
meter_events = {}
batches = {}
line_items = {}
load_allocations = {}

# Monotonic insertion sequence — used to order records deterministically when
# created_at timestamps tie (e.g. multiple meter events under a frozen clock).
_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())


def stamp_create(obj):
    """Attach common system fields (PRD §2.4): id, created_at, updated_at, version=1.

    Also records a monotonic _seq so creation order is a stable tiebreaker when
    created_at timestamps tie under a frozen test clock.
    """
    ts = now_iso()
    obj["id"] = new_id()
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    obj["_seq"] = next_seq()
    return obj


def touch(obj):
    """Record a mutation: refresh updated_at and bump version by 1 (PRD §2.4)."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj
