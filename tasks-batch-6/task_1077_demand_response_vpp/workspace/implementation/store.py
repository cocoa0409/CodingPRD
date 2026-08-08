"""In-memory data store, logical clock, id/timestamp minting.

Every process boot starts with an empty store and the logical clock reset to
the PRD default (2026-05-01T00:00:00Z). No entity is seeded at startup.
"""
import uuid
import random
import string
from datetime import datetime, timezone

# Collection name -> {id: record dict}. Records store only public output fields
# plus internal keys prefixed with "_" (stripped on serialization).
COLLECTIONS = [
    "programs", "aggregators", "customers", "devices", "enrollments",
    "dispatch_events", "dispatches", "meter_readings", "settlements", "payments",
]


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.data = {name: {} for name in COLLECTIONS}
        # PRD §2.10: logical clock defaults to 2026-05-01T00:00:00Z.
        self.current_utc = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def iso_z(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    """Logical-clock instant, used for created_at / updated_at."""
    return iso_z(db.current_utc)


def real_now_iso():
    """Wall-clock instant, used only for api_request_timestamp metadata."""
    return iso_z(datetime.now(timezone.utc))


def parse_iso(value):
    """Parse an ISO 8601 UTC string to an aware datetime, or raise ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def serialize(rec):
    """Public view: drop internal keys (prefixed with "_")."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
