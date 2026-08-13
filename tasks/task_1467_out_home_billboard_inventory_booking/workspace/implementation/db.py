"""In-memory store. Starts empty on every boot; no seeding, no persistence."""
import uuid

from util import clock_now, ts3

# One dict per entity type, keyed by id. Insertion order is creation order.
rate_cards = {}
faces = {}
permits = {}
work_orders = {}
advertisers = {}
campaigns = {}
flights = {}
artwork_orders = {}
posting_records = {}
make_goods = {}

_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_resource():
    """Common system fields (PRD 2.4): id, created_at, updated_at, version."""
    now = ts3(clock_now())
    return {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(res):
    """Record a modification: refresh updated_at, bump version (PRD 2.4)."""
    res["updated_at"] = ts3(clock_now())
    res["version"] += 1
