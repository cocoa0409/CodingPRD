"""In-memory data store. Starts EMPTY on every boot — no seeding."""
import itertools
import threading
import uuid
from datetime import datetime, timezone

_seq = itertools.count(1)
_lock = threading.Lock()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def next_seq():
    # Monotonic creation sequence to break created_at ties deterministically.
    return next(_seq)


class Store:
    """One dict per top-level collection. Empty on construction."""

    def __init__(self):
        self.service_jobs = {}
        self.technicians = {}
        self.job_bays = {}
        self.dispatches = {}
        self.bay_bookings = {}
        self.quotes = {}
        self.lock_parts = {}
        self.reservations = {}
        self.key_authorizations = {}
        self.payments = {}
        self.warranty_claims = {}


db = Store()
lock = _lock
