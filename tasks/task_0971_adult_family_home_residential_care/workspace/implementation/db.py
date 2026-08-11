"""In-memory data store + logical clock. Fresh, empty state on every boot."""

import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.homes = {}
        self.beds = {}
        self.residents = {}
        self.assessments = {}
        self.admissions = {}
        self.med_orders = {}
        self.med_logs = {}
        self.adl_logs = {}
        self.caregivers = {}
        self.shifts = {}
        self.incidents = {}
        self.cases = {}
        self.invoices = {}
        self.payments = {}
        self.rate_schedules = {}
        self.discharge_records = {}
        self.seq = 0
        # Logical clock: before ever set it reads exactly 2026-05-01T00:00:00Z
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

    def next_seq(self):
        self.seq += 1
        return self.seq

    def now(self):
        return self.clock

    def set_clock(self, dt):
        self.clock = dt


db = Store()


def new_id():
    return str(uuid.uuid4())
