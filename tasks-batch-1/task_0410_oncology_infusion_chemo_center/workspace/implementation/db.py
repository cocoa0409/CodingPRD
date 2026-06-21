"""In-memory data store. Starts empty on every boot — no seeding."""
import threading
import uuid
from datetime import datetime, timezone


# One dict per entity type, keyed by id.
_TABLES = [
    "patients",
    "regimen_protocols",
    "order_set_items",
    "chairs",
    "nurses",
    "prior_authorizations",
    "treatment_cycles",
    "drug_orders",
    "infusion_appointments",
    "toxicity_events",
]


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        for t in _TABLES:
            setattr(self, t, {})

    def reset(self):
        for t in _TABLES:
            setattr(self, t, {})


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    # ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"
