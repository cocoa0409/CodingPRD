"""In-memory data store. Starts EMPTY on every boot -- nothing is seeded.

No sqlite, no file writes, no /tmp cache, no json.dump, no pickle. Every entity
any test needs is constructed by the test through the declared API surface.
"""

import ids
from clock import CLOCK

COLLECTIONS = (
    "plans",
    "accounts",
    "members",
    "profiles",
    "identifiers",
    "brokers",
    "documents",
    "scans",
    "exposures",
    "removal_requests",
    "breach_events",
    "alerts",
    "findings",
    "addons",
    "seats",
    "cycles",
    "ledger",
)

# family key -> collection name, used by path resolution (PRD §2.5)
FAMILY_COLLECTION = {
    "plan": "plans",
    "account": "accounts",
    "member": "members",
    "profile": "profiles",
    "broker": "brokers",
    "scan": "scans",
    "exposure": "exposures",
    "removal_request": "removal_requests",
    "document": "documents",
    "breach_event": "breach_events",
    "alert": "alerts",
    "finding": "findings",
    "addon": "addons",
    "seat": "seats",
    "cycle": "cycles",
    "ledger_entry": "ledger",
}


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        ids.reset()
        CLOCK.reset()

    def all(self, collection):
        return list(getattr(self, collection).values())

    def get(self, collection, row_id):
        if not isinstance(row_id, str):
            return None
        return getattr(self, collection).get(row_id)

    def put(self, collection, row):
        getattr(self, collection)[row["id"]] = row
        return row


DB = Store()


def sort_key(row):
    """Deterministic list ordering: created_at ASC, id ASC as tie-break.

    Ids are monotonic (see ids.py), so the tie-break is creation order.
    """
    return (row["created_at"], row["id"])


def ordered(rows):
    return sorted(rows, key=sort_key)
