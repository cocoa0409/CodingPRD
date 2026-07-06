"""In-memory data store.

NO entity data is ever seeded or preloaded. Every collection starts empty on
process boot; tests build all state via the API. The logical clock starts at
the PRD §2.5 default 2026-03-01T00:00:00Z and never reads wall-clock time.
"""
import threading
import uuid
from datetime import datetime, timezone


CLOCK_DEFAULT = "2026-03-01T00:00:00Z"


def parse_iso(s):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _now_millis_iso():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # One dict per entity, keyed by id. ALL start empty.
        self.seasons = {}
        self.productions = {}
        self.venues = {}
        self.seats = {}
        self.performances = {}
        self.patrons = {}
        self.subscriptions = {}
        self.subscription_seats = {}
        self.tickets = {}
        self.donations = {}
        self.exchanges = {}
        self.auditions = {}
        # Logical clock (PRD §2.5): a stored ISO instant, default at boot.
        self.clock = parse_iso(CLOCK_DEFAULT)

    # ---- identity / timestamp / version helpers ----
    def new_id(self):
        return str(uuid.uuid4())

    def stamp_new(self, obj):
        """Initialize common system fields on a freshly created resource
        (PRD §2.4): created_at, updated_at, version starting at 1."""
        ts = _now_millis_iso()
        obj["created_at"] = ts
        obj["updated_at"] = ts
        obj["version"] = 1
        return obj

    def touch(self, obj):
        """Refresh updated_at and bump version by one on mutation (PRD §2.4/§2.8)."""
        obj["updated_at"] = _now_millis_iso()
        obj["version"] = obj.get("version", 1) + 1
        return obj


store = Store()
