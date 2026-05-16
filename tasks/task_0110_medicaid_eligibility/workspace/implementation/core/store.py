"""In-memory data store and ID helpers."""

import uuid
import threading


_LOCK = threading.RLock()


class Store:
    def __init__(self):
        # Keyed by id
        self.state_policies = {}          # id -> dict
        self.state_policies_by_code = {}  # state_code -> id
        self.emergency_declarations = {}  # id -> dict
        self.households = {}              # id -> dict
        self.applicants = {}              # id -> dict
        self.income_records = {}          # id -> dict
        self.asset_records = {}           # id -> dict
        self.applications = {}            # id -> dict
        self.determinations = {}          # id -> dict
        self.enrollments = {}             # id -> dict
        self.redeterminations = {}        # id -> dict
        self.appeals = {}                 # id -> dict
        self.fair_hearings = {}           # id -> dict
        self._seq = 0

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq


STORE = Store()


def lock():
    return _LOCK


def gen_id() -> str:
    return str(uuid.uuid4())


def gen_request_id() -> str:
    # Per PRD §2.2: starts with req_ followed by alphanumeric
    return "req_" + uuid.uuid4().hex[:20]
