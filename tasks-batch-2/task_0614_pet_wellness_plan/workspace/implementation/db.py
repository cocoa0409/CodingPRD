"""In-memory data store + logical clock.

The store starts EMPTY on every boot. No entity is seeded, preloaded, or
hardcoded at startup (skill checklist). Tests build every precondition via the
declared API surface.
"""
import uuid
from datetime import datetime, timezone

# Logical clock default (PRD §2.4): at server startup the logical clock reads
# exactly 2026-01-01T00:00:00Z and never falls back to wall-clock time.
CLOCK_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.plans = {}
        self.plan_services = {}
        self.clinics = {}
        self.member_accounts = {}
        self.memberships = {}
        self.enrolled_pets = {}
        self.contract_terms = {}
        self.service_credits = {}
        self.service_visits = {}
        self.billing_cycles = {}
        self.plan_change_requests = {}
        # Monotonic creation counter — stable insertion order independent of
        # logical-clock timestamp collisions (used as created_at tie-break).
        self._seq = 0
        # Logical clock (PRD §2.4).
        self.clock = CLOCK_DEFAULT
        # ClockState resource id (created lazily on first read/set).
        self.clock_id = str(uuid.uuid4())
        self.clock_created_at = iso(CLOCK_DEFAULT)

    def next_seq(self):
        self._seq += 1
        return self._seq


def iso(dt):
    """Format a datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


db = Store()


def new_id():
    return str(uuid.uuid4())


def clock_now():
    """The logical clock value as a datetime (PRD §2.4)."""
    return db.clock


def parse_iso(s):
    """Parse an ISO 8601 UTC string (with optional 'Z') into a datetime.

    Raises ValueError on malformed input (caller maps to ERR_INVALID_REQUEST).
    """
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_iso():
    """ISO string of the logical clock — used for created_at / updated_at and
    every system-minted timestamp. All time-dependent logic reads the logical
    clock rather than the host machine clock (PRD §2.4)."""
    return iso(db.clock)
