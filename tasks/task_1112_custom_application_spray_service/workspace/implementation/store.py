"""In-memory data store. Starts empty on every boot; the logical clock starts
at exactly 2026-05-01T00:00:00Z and never falls back to wall-clock time."""

import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = 0
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.customers = {}
        self.fields = {}
        self.products = {}
        self.compatibility_rules = {}
        self.prescriptions = {}
        self.applicators = {}
        self.equipment = {}
        self.calibration_records = {}
        self.weather_observations = {}
        self.work_orders = {}
        self.application_records = {}
        self.rinsate_records = {}
        self.drift_complaints = {}
        self.invoices = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()
