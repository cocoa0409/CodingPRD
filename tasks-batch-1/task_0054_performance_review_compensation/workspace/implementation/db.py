"""In-memory data store. Starts empty on every boot; no seeding."""
import itertools
import uuid
from datetime import datetime, timezone


def _now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.cycles = {}
        self.reviews = {}
        self.employees = {}
        self.goals = {}
        self.feedback_requests = {}
        self.calibration_sessions = {}
        self.comp_plans = {}
        self.pip_cases = {}
        self.rating_bands = {}
        # Monotonic counter to provide a stable creation order even if two
        # records share the same millisecond timestamp.
        self._seq = itertools.count(1)

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return db.new_id()


def now_iso():
    return _now_iso()
