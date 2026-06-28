"""In-memory data store. Every collection is a dict keyed by entity id.

The store starts EMPTY on every boot. Tests build all state via the API; nothing
is seeded or preloaded here.
"""

import threading
import uuid
from datetime import datetime, timezone

from clock import clock


def new_id():
    return str(uuid.uuid4())


def system_now_iso():
    """Wall-clock timestamp for created_at/updated_at and the response meta.

    PRD §2.4: created_at/updated_at are ISO 8601 UTC with three fractional digits,
    recorded at create/mutation. These are real server timestamps (monotonic enough
    to order list results), independent of the logical clock that gates business time.
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # One dict per entity type, keyed by id.
        self.protected_persons = {}
        self.fiduciaries = {}
        self.cases = {}
        self.petitions = {}
        self.evaluations = {}
        self.appointments = {}
        self.bonds = {}
        self.restricted_accounts = {}
        self.inventories = {}
        self.budgets = {}
        self.expenditures = {}
        self.accountings = {}
        self.care_plans = {}
        self.reviews = {}
        # Monotonic counter to break created_at ties deterministically.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# ---------------------------------------------------------------------------
# Common-field helpers (PRD §2.4): every entity carries id, created_at,
# updated_at, and version (starts at 1, increments by 1 on each mutation).
# ---------------------------------------------------------------------------
def stamp_create(record):
    now = system_now_iso()
    record["id"] = new_id()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def stamp_update(record):
    record["updated_at"] = system_now_iso()
    record["version"] = record.get("version", 0) + 1
    return record
