"""In-memory data store. The store starts empty on every boot — no seeding."""
import uuid
from datetime import datetime, timezone


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    """ISO 8601 UTC with three fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 timestamp that may end in 'Z'."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_utc(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        # Logical clock — startup default exactly 2026-08-01T00:00:00Z
        self.logical_clock: datetime = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

        self.sites: dict = {}
        self.technicians: dict = {}
        self.vessels: dict = {}
        self.level_readings: dict = {}
        self.quality_reports: dict = {}
        self.scale_calibrations: dict = {}
        self.replenishment_orders: dict = {}
        self.service_tickets: dict = {}
        self.entry_permits: dict = {}


# Module-level singleton store (reset on every fresh process boot).
store = Store()
