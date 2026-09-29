"""In-memory data store and the server-held logical clock.

Storage is process-local Python dicts keyed by entity id.  Nothing is
persisted and nothing is seeded: the store starts completely empty on every
boot and every entity is built by callers through the declared endpoints.
"""

import threading
import uuid
from datetime import datetime, timezone

# The logical clock's default value (PRD 2.6).
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "participants",
    "position_accounts",
    "ledger_entries",
    "liquidity_alerts",
    "segment_policies",
    "customer_accounts",
    "credit_transfers",
    "request_for_payments",
    "fraud_reviews",
    "return_requests",
    "settlement_cycles",
    "reconciliation_runs",
    "outage_events",
)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.clock = DEFAULT_CLOCK
        self._seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """The current logical clock instant (never the host wall clock)."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def new_record(with_version=True):
    """Allocate the system-managed common fields of a fresh record."""
    rec = {
        "id": new_id(),
        "_seq": db.next_seq(),
        "created_at": now(),
    }
    if with_version:
        rec["updated_at"] = now()
        rec["version"] = 1
    return rec


def bump(rec):
    """A mutation: version +1 and updated_at refreshed in the same step."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = now()
    return rec


def order_key(rec):
    """Stable ascending arrival order: created_at then insertion sequence."""
    return (rec["created_at"], rec["_seq"])


def rows(collection):
    return list(getattr(db, collection).values())


def sorted_rows(collection, reverse=False):
    return sorted(rows(collection), key=order_key, reverse=reverse)
