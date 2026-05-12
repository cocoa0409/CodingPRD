"""In-memory data store with a single global lock for serialization."""

import threading
import uuid


# A coarse-grained re-entrant lock keeps every mutating endpoint serialized,
# which is sufficient for the concurrency guarantees in PRD §2.7 and §2.10.
LOCK = threading.RLock()


class Store:
    def __init__(self):
        self.locker_machines = {}      # id -> dict
        self.compartments = {}         # id -> dict
        self.couriers = {}             # id -> dict
        self.parcels = {}              # id -> dict
        self.pickup_attempts = {}      # id -> dict
        self.fee_records = {}          # id -> dict
        self.disputes = {}             # id -> dict
        self.compartment_events = []   # ordered list of dicts
        self.audit_logs = []           # ordered list of dicts
        self.settlements = {}          # id -> dict

        # Indexes
        # parcel_id -> sorted list of fee_record ids by created_at asc
        self.parcel_fees = {}
        # parcel_id -> long_stay_at datetime
        self.parcel_long_stay_at = {}
        # parcel_id -> pickup_pending_at datetime
        self.parcel_pickup_pending_at = {}

    def reset(self):
        self.__init__()


DB = Store()


def new_id() -> str:
    return str(uuid.uuid4())
