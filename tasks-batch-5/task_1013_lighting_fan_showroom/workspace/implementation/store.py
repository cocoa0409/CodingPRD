"""In-memory data store + logical clock.

Every value lives in Python dicts on a single module-level singleton.
A fresh process (each per-test reboot) starts with an empty store and the
logical clock reset to the startup default 2026-07-01T00:00:00Z.
NO entities are ever seeded/preloaded here.
"""
import itertools
import uuid
from datetime import datetime, timezone

from timeutil import wall_now_iso

CLOCK_DEFAULT = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = [
    "trade_accounts",
    "fixture_models",
    "orders",
    "order_lines",
    "special_orders",
    "design_consults",
    "installers",
    "install_referrals",
    "delivery_trucks",
    "delivery_jobs",
    "return_requests",
    "rebate_programs",
    "rebate_claims",
]


class DB:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = itertools.count(1)
        self.clock = CLOCK_DEFAULT

    def next_seq(self):
        return next(self._seq)


db = DB()


def new_id():
    return str(uuid.uuid4())


def new_base():
    ts = wall_now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(rec):
    """Record a mutation: refresh updated_at and bump version."""
    rec["updated_at"] = wall_now_iso()
    rec["version"] += 1


def insert(collection_name, rec):
    getattr(db, collection_name)[rec["id"]] = rec
    return rec


def fetch(collection_name, rec_id):
    """Path-referenced lookup: raise ERR_NOT_FOUND (404) when absent."""
    from errors import err

    rec = getattr(db, collection_name).get(rec_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return rec


def fk(collection_name, rec_id):
    """Body foreign-key lookup: raise ERR_FK_NOT_FOUND (404) when absent."""
    from errors import err

    rec = getattr(db, collection_name).get(rec_id)
    if rec is None:
        raise err("ERR_FK_NOT_FOUND", "Referenced entity not found")
    return rec
