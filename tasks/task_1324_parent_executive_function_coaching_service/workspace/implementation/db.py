"""In-memory data store and logical clock.

The store starts completely empty on every boot. No seeding, no preload.
The logical clock starts at exactly 2026-08-01T00:00:00Z and only moves via
POST /api/_clock/set_current_utc; it never falls back to wall-clock time.
"""
import uuid
from datetime import datetime, timezone

# Entity tables: dicts keyed by id.
families = {}
clients = {}
coaches = {}
intakes = {}
plans = {}
goals = {}
packages = {}
sessions = {}
checkins = {}
snapshots = {}
contacts = {}
consents = {}
notes = {}
workshops = {}
enrollments = {}
supervision_records = {}

# Logical clock (timezone-aware UTC datetime). Startup default per PRD §2.4.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# Monotonic insertion sequence. The logical clock makes created_at ties the
# norm (many entities share one instant), so every "by creation" ordering —
# list sorting, waitlist positions, cadence "created last" tie-breaks — uses
# this sequence as the deterministic tiebreak instead of the random UUID.
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso(clock)
