import threading
import uuid
from datetime import datetime, timezone, timedelta


class Clock:
    """Logical server clock. Defaults to real UTC; settable for tests."""

    def __init__(self):
        self._override = None

    def now(self):
        if self._override is not None:
            return self._override
        return datetime.now(timezone.utc)

    def set(self, dt):
        self._override = dt


clock = Clock()
_lock = threading.RLock()


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and trailing Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 string into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Store:
    """In-memory store. One dict per entity type, keyed by id."""

    def __init__(self):
        self.owners = {}
        self.vehicles = {}
        self.vin_verifications = {}
        self.title_applications = {}
        self.salvage_inspections = {}
        self.liens = {}
        self.emissions_inspections = {}
        self.fee_assessments = {}
        self.registrations = {}
        self.license_plates = {}
        self.real_id_applications = {}

    def lock(self):
        return _lock


db = Store()
EMISSIONS_VALID_DAYS = 365
REGISTRATION_TERM_DAYS = 365
