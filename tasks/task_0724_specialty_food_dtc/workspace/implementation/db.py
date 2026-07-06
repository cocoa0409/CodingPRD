"""In-memory data store. Starts EMPTY on every boot. No seeding."""
import itertools
import uuid

from clock import clock, to_iso


class DB:
    def __init__(self):
        self.customers = {}
        self.skus = {}
        self.lots = {}
        self.subscriptions = {}
        self.orders = {}
        self.order_lines = {}
        self.bulk_quotes = {}
        self.referrals = {}
        self.winback_offers = {}
        self._seq = itertools.count(1)

    def new_id(self):
        return str(uuid.uuid4())

    def seq(self):
        return next(self._seq)


db = DB()


def new_common():
    """Common fields at creation: created_at, updated_at, version, plus a monotonic
    creation sequence used for stable created_at-ascending ordering and FEFO tie-break."""
    ts = to_iso(clock.now())
    return {
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.seq(),
    }


def touch(entity):
    """Mutation: refresh updated_at, bump version."""
    entity["updated_at"] = to_iso(clock.now())
    entity["version"] = entity.get("version", 1) + 1


def public(entity):
    """Strip internal fields (those prefixed with '_') from an entity for output."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}
