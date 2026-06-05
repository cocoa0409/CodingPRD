"""In-memory data store + logical clock.

The store starts EMPTY on every boot. No seeding of any kind. Tests build all
preconditions through the declared API surface.

The platform never reads the host wall clock for time-sensitive decisions; it
maintains a single logical ClockState (PRD §2.4) whose current_utc begins at
1970-01-01T00:00:00.000Z and is advanced only via POST /_clock/set.
"""
import threading
import uuid
from datetime import datetime, timezone

# Per-resource maps keyed by id.
physicians = {}
state_licenses = {}
patients = {}
payers = {}
visits = {}
compliance_checks = {}
prescriptions = {}
claims = {}
follow_ups = {}

# Logical clock (single object; PRD §2.4).
CLOCK_EPOCH = "1970-01-01T00:00:00.000Z"
clock = {
    "id": None,        # minted lazily on first read/set
    "current_utc": CLOCK_EPOCH,
    "created_at": None,
}

# Single global lock — the platform is consistency_model: immediate. Each request
# mutates under this lock so cascades are atomic relative to concurrent reads.
lock = threading.RLock()


def new_id():
    return str(uuid.uuid4())


# Monotonic creation sequence. Records are minted under the global lock, so a
# plain incrementing counter gives a stable, append-order tie-break for list
# ordering when two records share the same logical-clock created_at millisecond
# (PRD §2.3 "sorted by created_at ascending"; PRD §2.8 the ComplianceCheck log
# is append-only, so its chronology is its insertion order). The random UUID id
# must never be the ordering tie-break.
_seq_counter = 0


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def now_dt():
    return datetime.now(timezone.utc)


def iso_millis(dt=None):
    if dt is None:
        dt = now_dt()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime.

    Accepts trailing 'Z' and +HH:MM offsets. Returns None if unparseable.
    """
    if value is None or not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Fall back: maybe date-only or no offset → treat as UTC.
        try:
            dt = datetime.strptime(value.strip().rstrip("Z"), "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            try:
                dt = datetime.strptime(value.strip(), "%Y-%m-%d")
            except ValueError:
                return None
        dt = dt.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_now():
    """Current logical-clock instant as an aware UTC datetime."""
    return parse_iso(clock["current_utc"])


def reset():
    """Wipe the store. Used only for test harness symmetry; not invoked at boot."""
    for d in (physicians, state_licenses, patients, payers, visits,
              compliance_checks, prescriptions, claims, follow_ups):
        d.clear()
    clock["id"] = None
    clock["current_utc"] = CLOCK_EPOCH
    clock["created_at"] = None
