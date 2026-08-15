"""In-memory data store and logical clock."""

import uuid
import threading
from datetime import datetime, timezone


class LogicalClock:
    """Server-side logical clock. Startup default: 2026-08-01T00:00:00Z."""

    DEFAULT = "2026-08-01T00:00:00+00:00"

    def __init__(self):
        self._lock = threading.Lock()
        self._now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def set(self, dt: datetime):
        with self._lock:
            self._now = dt

    def now_iso(self) -> str:
        """Return current logical time as ISO8601 with 'Z' suffix."""
        dt = self.now()
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

    def now_date(self):
        return self.now().date()


class Store:
    """In-memory store. Starts completely empty on every boot."""

    def __init__(self):
        self.clock = LogicalClock()
        # entity name -> { id: dict }
        self.productions = {}
        self.jurisdictions = {}
        self.locations = {}
        self.location_owners = {}
        self.location_bookings = {}
        self.scout_packages = {}
        self.owner_agreements = {}
        self.permit_applications = {}
        self.street_closures = {}
        self.notification_records = {}
        self.insurance_certificates = {}
        self.deposit_accounts = {}
        self.walkthrough_reports = {}
        self.monitor_assignments = {}
        self.shoot_days = {}
        self.complaints = {}


def new_id() -> str:
    return str(uuid.uuid4())


def iso_now(clock: LogicalClock) -> str:
    return clock.now_iso()


# Singleton store instance
store = Store()
