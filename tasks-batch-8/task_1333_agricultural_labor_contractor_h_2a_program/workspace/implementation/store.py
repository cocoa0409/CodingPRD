"""In-memory data store. Starts completely empty on every boot; the logical
clock defaults to 2026-08-01T00:00:00Z and never falls back to wall-clock."""

import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0
        self.growers = {}
        self.wage_determinations = {}
        self.job_orders = {}
        self.domestic_applications = {}
        self.workers = {}
        self.visa_petitions = {}
        self.consular_appointments = {}
        self.housing_units = {}
        self.housing_inspections = {}
        self.housing_assignments = {}
        self.worker_assignments = {}
        self.work_logs = {}
        self.wage_reconciliations = {}
        self.transfer_requests = {}
        self.audit_cases = {}


db = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    db.seq += 1
    return db.seq
