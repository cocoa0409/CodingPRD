"""In-memory data store and ID generation."""

import threading
import uuid


class DB:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        # Keyed by id (UUID string)
        self.pesticide_registry: dict = {}            # registration_no -> registry
        self.planting_batches: dict = {}              # id -> batch
        self.agrochemical_applications: dict = {}     # id -> application
        self.harvest_records: dict = {}               # id -> harvest record
        self.storage_bins: dict = {}                  # id -> bin
        self.logistics_legs: dict = {}                # id -> leg
        self.sensor_readings: dict = {}               # id -> reading
        self.inspection_reports: dict = {}            # id -> report
        self.qr_codes: dict = {}                      # id -> qr
        self.qr_by_value: dict = {}                   # qr_code_value -> id
        self.qr_by_harvest: dict = {}                 # harvest_record_id -> id
        self.distributors: dict = {}                  # id -> distributor
        self.recall_orders: dict = {}                 # id -> recall
        self.audit_logs: list = []                    # append-only

        # Idempotency map for sensor readings:
        # (logistics_leg_id, idempotency_key) -> sensor_reading id
        self.sensor_idempotency: dict = {}

        # Notification events emitted by recall.notify (for inspection in tests if needed).
        self.notifications: list = []

    def new_id(self) -> str:
        return str(uuid.uuid4())


db = DB()
