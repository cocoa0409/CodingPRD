"""In-memory data store. Empty on every boot — no seeding."""
import uuid
from datetime import datetime, timezone, timedelta

# ---------------- logical clock ----------------
_DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": _DEFAULT_CLOCK}


def now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def fmt_ts(dt):
    """ISO 8601 UTC with 3 fractional digits, e.g. 2026-05-01T00:00:00.000Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_ts(s):
    """Parse ISO 8601 timestamp (with Z or offset) into aware datetime."""
    if isinstance(s, datetime):
        return s
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def new_id():
    return str(uuid.uuid4())


# ---------------- ledger sequence ----------------
# Ledger entries can share the same logical-clock `created_at` (the clock only
# advances via the test-driving endpoint). We attach a monotonically
# increasing sequence number so "newest first" remains deterministic.
_ledger_seq = {"n": 0}


def next_ledger_seq():
    _ledger_seq["n"] += 1
    return _ledger_seq["n"]


# ---------------- entity stores (all empty at boot) ----------------
programs = {}
caregivers = {}
applications = {}
allocations = {}
vouchers = {}
providers = {}
windows = {}
bookings = {}
visits = {}
claims = {}
ledger = {}
emergencies = {}
surveys = {}
snapshots = {}


def new_common():
    """Return the four system-managed common fields for a fresh entity."""
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(entity):
    """Bump updated_at and version by exactly 1 on mutation."""
    entity["updated_at"] = now()
    entity["version"] += 1
