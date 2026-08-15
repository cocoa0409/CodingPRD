"""In-memory data store. Starts empty on every boot -- no seeding."""
import uuid
from datetime import datetime, timezone, timedelta


def _utcnow_iso():
    """Real wall-clock timestamp for created_at/updated_at metadata."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


class Clock:
    """Logical clock. Starts at 2026-08-01T00:00:00Z. Never falls back to wall clock."""

    def __init__(self):
        self._current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._current

    def today(self):
        return self._current.date()

    def set(self, iso: str):
        s = iso.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._current = dt.astimezone(timezone.utc)

    def iso(self) -> str:
        dt = self._current
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.clock = Clock()
        self.contractor_accounts = {}   # id -> dict
        self.products = {}              # id -> dict
        self.projects = {}              # id -> dict
        self.takeoffs = {}              # id -> dict
        self.takeoff_lines = {}         # id -> dict
        self.stocking_orders = {}       # id -> dict
        self.stocking_drops = {}        # id -> dict
        self.boom_trucks = {}           # id -> dict
        self.draw_requests = {}         # id -> dict
        self.payments = {}              # id -> dict
        self.bundle_returns = {}        # id -> dict


db = Store()
