"""In-memory data store and clock. Starts empty on every boot."""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.owners = {}
        self.trainers = {}
        self.dogs = {}
        self.vaccinations = {}
        self.behavioral_intakes = {}
        self.class_series = {}
        self.class_sessions = {}
        self.enrollments = {}
        self.packages = {}
        self.package_redemptions = {}
        self.attendance_records = {}
        self.makeup_bookings = {}
        self.certificates = {}
        # Logical server clock. None => use real wall clock.
        self._clock = None

    # ---- clock ----
    def set_clock(self, dt):
        self._clock = dt

    def current_clock(self):
        if self._clock is not None:
            return self._clock
        return datetime.now(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# Single global store instance, recreated fresh per process.
db = Store()
