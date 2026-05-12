"""In-memory data store with simple uuid + lock primitives."""
import uuid
import threading
from collections import defaultdict


def new_id() -> str:
    return str(uuid.uuid4())


# Global write lock (the test suites rely on concurrency serialization).
GLOBAL_LOCK = threading.RLock()


class Store:
    def __init__(self):
        # Top-level tables keyed by id
        self.stations = {}             # id -> dict
        self.shelf_zones = {}          # id -> dict
        self.staff = {}                # id -> dict
        self.parcels = {}              # id -> dict
        self.pickup_codes = {}         # id -> dict
        self.pickup_auths = {}         # id -> dict
        self.reminders = {}            # id -> dict
        self.return_shipments = {}     # id -> dict
        self.billing_periods = {}      # id -> dict
        self.bills = {}                # id -> dict
        self.quality_assessments = {}  # id -> dict
        self.audit_events = {}         # id -> dict
        self.system_events = {}        # id -> dict

        # Indexes
        self.billing_period_by_key = {}    # (station_id, period_yyyymm) -> id
        self.quality_assessment_by_key = {}  # (station_id, period_yyyymm) -> id

        # Payment idempotency table: (bill_id, idempotency_key) -> stored bill snapshot
        self.payment_idempotency = {}

        # Outbox sequence counters
        self.outbox_seq = defaultdict(int)  # (subject_kind, subject_id) -> last_seq


store = Store()
