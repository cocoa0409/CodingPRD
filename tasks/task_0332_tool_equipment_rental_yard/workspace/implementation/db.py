"""In-memory data store.

PRD §2.10 / scaffold: storage is in-memory only. Every dict is keyed by the
entity id. No seeding occurs at startup — the store is empty on every boot and
all entities are constructed by tests through the declared endpoints.

The store is process-global; a fresh process (start.sh re-invocation) wipes all
state.
"""
import threading
import uuid
from datetime import datetime, timezone


# A single big lock serializes every mutation. The domain's "immediate"
# consistency model plus state/temporal preconditions (PRD §2.10) require that a
# strictly-sequential second request observes the first's committed state.
LOCK = threading.RLock()


class Store:
    def __init__(self):
        # Each collection: id -> record dict.
        self.rate_cards = {}
        self.catalog_items = {}
        self.equipment_units = {}
        self.contractor_accounts = {}
        self.delivery_trucks = {}
        self.reservations = {}
        self.rental_agreements = {}
        self.return_inspections = {}
        self.maintenance_tickets = {}
        self.damage_charges = {}
        self.ledger_entries = {}
        # Singleton yard clock; default current_utc per PRD §2.7.
        self.yard_clock = None
        # Monotonic insertion counter to break created_at ties deterministically.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


DB = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD §2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def ensure_clock():
    """Return the singleton YardClock, creating it lazily with the PRD default.

    PRD §2.7: YardClock.current_utc defaults to 1970-01-01T00:00:00.000Z until
    set. The clock is a singleton record carrying only id/created_at (PRD §2.4).
    """
    if DB.yard_clock is None:
        DB.yard_clock = {
            "id": new_id(),
            "created_at": now_iso(),
            "current_utc": "1970-01-01T00:00:00.000Z",
        }
    return DB.yard_clock
