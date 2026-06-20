"""In-memory data store. Starts empty on every boot — no seeding."""
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.programs = {}
        self.jurisdictions = {}
        self.conditions = {}
        self.cases = {}
        self.lab_results = {}
        self.contacts = {}
        self.exposure_events = {}
        self.monitoring_periods = {}
        self.transfers = {}
        self.clusters = {}
        self.exports = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
