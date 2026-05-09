"""In-memory data store and helpers."""
import threading
import uuid
from datetime import datetime, timezone


def new_id() -> str:
    """36-character UUID with no entity prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """ISO 8601 UTC timestamp with three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S") + f".{n.microsecond // 1000:03d}Z"


class DB:
    def __init__(self):
        # Top-level dictionaries keyed by id
        self.programs: dict = {}            # HousingProgram
        self.applications: dict = {}        # Application
        self.housing_units: dict = {}       # HousingUnit
        self.allocations: dict = {}         # Allocation
        self.objections: dict = {}          # Objection
        self.contracts: dict = {}           # Contract
        self.rent_reductions: dict = {}     # RentReduction
        self.annual_reviews: dict = {}      # AnnualReview
        self.sync_events: dict = {}         # SyncEvent

        # Append-order list of sync_event ids (so "latest" lookups are stable)
        self.sync_event_order: list = []

        # A coarse-grained re-entrant lock to serialize state-changing operations,
        # making the optimistic-concurrency / first-writer-wins guarantees explicit.
        self.lock = threading.RLock()


db = DB()
