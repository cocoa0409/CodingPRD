"""In-memory data store.

The store is empty on every boot: no entity is ever seeded, preloaded or
hardcoded. Every row is created by a request against the declared API surface.
"""
import itertools
import uuid

from clock import clock, format_datetime


class Store:
    COLLECTIONS = (
        "offer_plans",
        "paywall_rules",
        "articles",
        "readers",
        "subscriptions",
        "invoices",
        "payment_attempts",
        "reader_events",
        "cancellation_requests",
        "save_offers",
        "holds",
        "group_accounts",
        "seats",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_entity(common_fields=True):
    """Create the system-managed property set (PRD 2.5)."""
    now = clock.now()
    entity = {
        "id": new_id(),
        "created_at": format_datetime(now),
        "_created_dt": now,
        "_seq": db.next_seq(),
    }
    if common_fields:
        entity["updated_at"] = format_datetime(now)
        entity["version"] = 1
    return entity


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])
