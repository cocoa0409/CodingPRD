"""In-memory data store.

Every entity collection is a dict keyed by id. The store starts EMPTY on every
process boot; nothing is seeded. Tests build all required state via the API.

Common system fields (PRD 2.4):
  - id: server-minted UUID, no type prefix
  - created_at: ISO timestamp set at create
  - updated_at: ISO timestamp refreshed on every mutation
  - version: integer starting at 1, +1 on every mutation

Two entity types are immutable append-only and carry only id + created_at:
EligibilitySpan and RateSchedule (no updated_at / no version).
"""
import itertools
import uuid

from clock import now_iso

# Process-wide monotonic insertion sequence. The server clock is frozen during
# tests, so many entities share an identical created_at; this sequence provides
# a stable insertion-order tiebreak for selection and list sorting (matches the
# order tests create entities in, e.g. the assigned driver is the one created
# first).
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


class DB:
    def __init__(self):
        self.members = {}
        self.eligibility_spans = {}
        self.brokers = {}
        self.drivers = {}
        self.rate_schedules = {}
        self.trips = {}
        self.legs = {}
        self.assignments = {}
        self.standing_orders = {}
        self.claims = {}
        self.encounters = {}
        # Symmetric county distance matrix: county_distance[a][b] = miles
        self.county_distance = {}

    def reset(self):
        self.__init__()


db = DB()


def new_id():
    return str(uuid.uuid4())


def new_common():
    """Common system fields for full entities. `_seq` is an internal
    insertion-order key (stripped before serialization)."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def new_immutable_common():
    """System fields for append-only immutable entities (id + created_at only).
    `_seq` is an internal insertion-order key (stripped before serialization)."""
    return {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
    }


def touch(entity):
    """Record a mutation: bump updated_at and version (PRD 2.4 / 2.5)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def set_county_distance(a, b, miles):
    db.county_distance.setdefault(a, {})[b] = miles
    db.county_distance.setdefault(b, {})[a] = miles


def get_county_distance(a, b):
    if a == b:
        return 0
    return db.county_distance.get(a, {}).get(b)
