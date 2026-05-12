"""In-memory data store with global lock for serialization."""

import threading
import uuid
from datetime import timezone


# Coarse-grained lock — sufficient for the concurrency guarantees in PRD §2.10.
LOCK = threading.RLock()


class Store:
    def __init__(self):
        self.tenants = {}
        self.plots = {}
        self.sensors = {}
        self.sensor_readings = {}      # by id
        self.readings_by_sensor = {}   # sensor_id -> list of reading ids (insertion order)
        self.irrigation_plans = {}
        self.valve_groups = {}
        self.control_commands = {}
        self.water_quotas = {}
        self.alerts = {}
        self.water_bills = {}
        self.audit_logs = []           # append-only list

        # Cached per-plot rainfall (mm) most recently emitted via /_events/emit.
        self.cached_rainfall_mm = {}   # plot_id -> mm (float)

    def reset(self):
        self.__init__()


DB = Store()


def new_id() -> str:
    return str(uuid.uuid4())


def from_iso(value):
    if value is None:
        return None
    from datetime import datetime
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
