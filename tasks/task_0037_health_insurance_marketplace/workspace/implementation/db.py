import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def iso_ts():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.households = {}
        self.members = {}
        self.health_plans = {}
        self.applications = {}
        self.determinations = {}
        self.enrollments = {}
        self.sep_requests = {}
        self.reconciliations = {}
        # monotonic sequence for stable created_at ordering ties
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()
