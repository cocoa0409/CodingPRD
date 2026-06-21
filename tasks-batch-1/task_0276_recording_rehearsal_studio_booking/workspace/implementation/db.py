"""In-memory data store. Wiped on every process boot — no seeding.

All entities are stored in plain dicts keyed by id. The logical Clock is a
server-controlled singleton (PRD §2.11).
"""
import uuid
from datetime import datetime, timezone, timedelta


def new_id():
    return str(uuid.uuid4())


def now_iso_millis(dt=None):
    """ISO 8601 UTC timestamp with three fractional digits."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    """A typed collection keyed by id, preserving insertion order."""

    def __init__(self):
        # entity-type -> {id: record}
        self.studios = {}
        self.rooms = {}
        self.engineers = {}
        self.gear_items = {}
        self.clients = {}
        self.bookings = {}
        self.gear_rentals = {}
        self.engineer_assignments = {}
        self.overtime_records = {}
        self.payments = {}
        self.lockout_contracts = {}
        self.session_deliveries = {}
        # monotonically increasing counter to keep a stable creation order even
        # when multiple records share the same wall-clock millisecond.
        self._seq = 0
        # logical clock singleton (PRD §2.11)
        self.clock = None

    def next_seq(self):
        self._seq += 1
        return self._seq


# Single global store instance. Recreated fresh on every process start, so
# state never carries across the per-test-server reboots.
db = Store()


def init_clock():
    """Initialise the server-controlled wall clock at real wall time."""
    real_now = datetime.now(timezone.utc)
    db.clock = {
        "id": new_id(),
        "current_utc": db_iso(real_now),
        "created_at": now_iso_millis(real_now),
    }


def db_iso(dt):
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    return now_iso_millis(dt)


def clock_now():
    """Return the current logical clock instant as an aware datetime."""
    from timeutil import parse_iso
    return parse_iso(db.clock["current_utc"])
