"""In-memory data store + logical clock + helpers."""
import uuid
from datetime import datetime, timezone


DEFAULT_CLOCK_ISO = "2026-03-01T00:00:00Z"


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        # Entity dicts keyed by id
        self.plans = {}
        self.products = {}
        self.clients = {}
        self.subscriptions = {}
        self.locations = {}
        self.preferences = {}
        self.par_levels = {}
        self.rotation_cycles = {}
        self.deliveries = {}
        self.delivery_lines = {}
        self.invoices = {}
        self.feedback = {}
        # Logical clock (mutable ISO string)
        self._clock_iso = DEFAULT_CLOCK_ISO

    # ---- clock -----------------------------------------------------------
    def set_clock(self, iso: str):
        # Normalize; accept a few common ISO forms
        self._clock_iso = normalize_iso(iso)

    def now(self) -> datetime:
        return parse_iso(self._clock_iso)

    def now_iso(self) -> str:
        # Reformat to 3-fractional-digit ISO for storage
        return iso_from_datetime(self.now())


STORE = Store()


# --- ID + timestamp helpers -----------------------------------------------
def new_id() -> str:
    return str(uuid.uuid4())


def iso_from_datetime(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s: str) -> datetime:
    if s is None:
        return None
    # Normalize trailing Z to +00:00 for fromisoformat
    if s.endswith("Z"):
        s2 = s[:-1] + "+00:00"
    else:
        s2 = s
    try:
        dt = datetime.fromisoformat(s2)
    except ValueError:
        # Fallback: try without fractional
        raise
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_iso(s: str) -> str:
    return iso_from_datetime(parse_iso(s))


def add_days(dt: datetime, days: int) -> datetime:
    from datetime import timedelta
    return dt + timedelta(days=days)


def add_hours(dt: datetime, hours: float) -> datetime:
    from datetime import timedelta
    return dt + timedelta(hours=hours)
