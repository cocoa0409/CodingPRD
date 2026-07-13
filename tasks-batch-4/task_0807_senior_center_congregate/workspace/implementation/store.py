"""In-memory data store, logical clock, and id/timestamp helpers.

The store is a fresh empty singleton on every process boot. Nothing is seeded,
preloaded, or hardcoded — every entity is created through the declared API.
"""
import random
import string
import uuid
from datetime import datetime, timezone

# The logical clock default, per PRD 2.8. Never falls back to real wall-clock.
DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


def new_id():
    """Server-minted opaque UUID string carrying no type prefix."""
    return str(uuid.uuid4())


def _fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    """Wall-clock UTC timestamp for created_at / updated_at / request meta."""
    return _fmt(datetime.now(timezone.utc))


def iso_of(dt):
    return _fmt(dt)


def request_id():
    alph = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alph) for _ in range(20))


class Store:
    def __init__(self):
        self.participants = {}
        self.grants = {}
        self.donations = {}
        self.funded_services = {}
        self.rooms = {}
        self.sessions = {}
        self.signups = {}
        self.vehicles = {}
        self.transports = {}
        self.service_days = {}
        self.reservations = {}
        self.programs = {}
        self.enrollments = {}
        self.volunteer_shifts = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def base_common(with_version=True):
    """Common bookkeeping fields for a freshly created entity."""
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version by exactly 1 on a mutation."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
