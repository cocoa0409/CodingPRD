"""In-memory data store and the logical server clock (PRD §2.4).

The store starts EMPTY on every boot — no seeding. The logical clock starts at
exactly 2026-08-01T00:00:00Z and is only advanced via POST /_clock/set_current_utc.
"""
import threading
import uuid
from datetime import datetime, timezone

_LOCK = threading.RLock()

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_START_ISO = "2026-08-01T00:00:00Z"


def _parse_iso(value):
    """Parse an ISO-8601 timestamp into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Returns None on malformed input.
    """
    if not isinstance(value, str):
        return None
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fmt_iso(dt):
    """Format an aware UTC datetime as ISO-8601 with three fractional digits + Z.

    Used for `created_at` / `updated_at` / `api_request_timestamp`, the fields
    PRD §2.2/§2.5 explicitly pin to three fractional digits.
    """
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


def _fmt_clock(dt):
    """Format a logical-clock-stamped instant the way the clock itself reads.

    PRD §2.4: "the logical clock reads exactly `2026-08-01T00:00:00Z`" — the
    clock's reading carries no fractional part at whole-second instants, and
    operations that stamp the current time (§2.4: `processed_at`,
    `checked_in_at`, `in_ground_at`, `completed_at`, `actual_departure_utc`,
    `last_inspection_at`) all read this same clock. Fractional digits appear
    only when the stamped instant actually carries them.
    """
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        base += f".{dt.microsecond // 1000:03d}"
    return base + "Z"


class _Clock:
    def __init__(self):
        self._now = _parse_iso(_START_ISO)

    def now(self):
        return self._now

    def now_iso(self):
        return _fmt_iso(self._now)

    def now_clock_iso(self):
        """The clock's own reading (PRD §2.4) — used for business-time stamps."""
        return _fmt_clock(self._now)

    def set(self, dt):
        self._now = dt
        return self._now


CLOCK = _Clock()


def now():
    return CLOCK.now()


def now_iso():
    return CLOCK.now_iso()


def now_clock_iso():
    """Current logical-clock reading in the clock's own format (PRD §2.4)."""
    return CLOCK.now_clock_iso()


# ---------------------------------------------------------------------------
# Stores — keyed by id, start empty on every boot
# ---------------------------------------------------------------------------
terminals = {}
pools = {}
chassis = {}
memberships = {}
carriers = {}
containers = {}
slots = {}
trains = {}
appointments = {}
transactions = {}
damage = {}
ledger = {}


def new_id():
    return str(uuid.uuid4())


def touch(resource):
    """Bump updated_at and version on any mutation (PRD §2.5)."""
    resource["updated_at"] = now_iso()
    resource["version"] = resource.get("version", 0) + 1


def stamp_new(resource):
    """Initialize the four common fields on a freshly created resource."""
    ts = now_iso()
    resource.setdefault("id", new_id())
    resource["created_at"] = ts
    resource["updated_at"] = ts
    resource["version"] = 1
    return resource
