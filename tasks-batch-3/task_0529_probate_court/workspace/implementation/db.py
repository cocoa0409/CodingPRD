"""In-memory data store and logical clock. Starts empty on every boot."""
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = "2026-05-01T00:00:00Z"


class Store:
    def __init__(self):
        # One dict per entity type, keyed by id.
        self.estates = {}
        self.petitions = {}
        self.representatives = {}
        self.bonds = {}
        self.beneficiaries = {}
        self.claims = {}
        self.assets = {}
        self.distributions = {}
        self.accountings = {}
        self.hearings = {}
        # Logical clock (a datetime, tz-aware UTC).
        self.clock = parse_iso(DEFAULT_CLOCK)

    def collection(self, name):
        return getattr(self, name)


def new_id():
    return str(uuid.uuid4())


def now_iso_from(dt):
    """Format a tz-aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_now_iso():
    return now_iso_from(datetime.now(timezone.utc))


def parse_iso(value):
    """Parse an ISO 8601 datetime string; return tz-aware UTC datetime or raise ValueError."""
    if not isinstance(value, str) or not value:
        raise ValueError("bad datetime")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


store = Store()


def reset():
    global store
    store = Store()
