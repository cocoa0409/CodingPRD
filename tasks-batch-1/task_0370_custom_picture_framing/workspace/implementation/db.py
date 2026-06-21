"""In-memory data store. State is process-local and wiped on every restart.

NOTE: No seeding here. The store starts empty on every boot; tests build all
preconditions through the declared API surface.
"""
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.customers = {}
        self.workbenches = {}
        self.framing_orders = {}
        self.frame_lines = {}
        self.production_tasks = {}
        self.payments = {}
        self.notifications = {}
        # Per-customer chronological settled outcome history.
        # Each entry: {"outcome": "ONTIME"|"ABANDON", "at": <iso ts string>}
        # (kept implicitly by replaying terminal orders; see services.scoring)


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    # ISO 8601 UTC with exactly 3 fractional digits, trailing Z.
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def request_id():
    return "req_" + uuid.uuid4().hex
