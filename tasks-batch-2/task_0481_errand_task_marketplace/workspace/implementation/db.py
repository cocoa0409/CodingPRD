"""In-memory data store and the server logical clock.

Storage is process-local Python dicts keyed by id. Nothing is persisted and
nothing is seeded — every record is created by an explicit API call. A fresh
process (each start.sh reboot) therefore begins with empty stores and the
default logical clock.
"""
import uuid
from datetime import datetime, timezone

# Default logical clock per PRD §2.4 / SCAFFOLD §1.5: 2026-01-01T00:00:00Z.
DEFAULT_CLOCK_ISO = "2026-01-01T00:00:00Z"


def new_id():
    return str(uuid.uuid4())


def parse_iso(value):
    """Parse an ISO 8601 instant (accepts trailing 'Z') into a tz-aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_millis(dt):
    """Render a tz-aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        # One dict per top-level / child entity, keyed by id.
        self.task_categories = {}
        self.taskers = {}
        self.tasker_skills = {}
        self.availability_windows = {}
        self.clients = {}
        self.recurring_series = {}
        self.bookings = {}
        self.settlements = {}
        self.cancellations = {}
        self.chat_messages = {}
        self.reviews = {}
        self.trust_incidents = {}

        # Logical clock — a tz-aware datetime, default 2026-01-01T00:00:00Z.
        self.clock = parse_iso(DEFAULT_CLOCK_ISO)

        # Monotonic creation sequence so created_at ties break deterministically
        # even when many records share the same logical-clock timestamp.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def clock_now():
    return db.clock
