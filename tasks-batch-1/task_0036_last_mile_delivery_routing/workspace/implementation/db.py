"""In-memory data store. Starts empty on every boot; no seeding."""
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.transit_centers = {}
        self.drivers = {}
        self.parcels = {}
        self.routes = {}
        self.stops = {}
        self.attempts = {}
        self.appointments = {}

    def new_id(self):
        return str(uuid.uuid4())


def now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


db = Store()
