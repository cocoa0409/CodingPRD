"""In-memory data store. Every byte of state is wiped on each process start.

NEVER seeded — tests build all state via the API surface.
"""
import uuid
import threading
from datetime import datetime, timezone

# Logical clock: PRD §2.6 — startup default exactly 2026-01-01T00:00:00Z.
# Until explicitly set, it stays at this default and never falls back to wall-clock.
DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

# A single global lock to make multi-step operations atomic.
LOCK = threading.RLock()


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.artists = {}
        self.portfolio_items = {}
        self.events = {}
        self.faces = {}
        self.trials = {}
        self.contracts = {}
        self.assignments = {}
        self.addons = {}
        self.invoices = {}
        self.payments = {}
        self.cancellations = {}
        self.clock_now = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Current logical-clock-independent wall timestamp for created_at/updated_at?

    PRD §2.4 says created_at/updated_at record creation/modification time. The
    api_request_timestamp (§2.2) is server-generated. We use wall-clock UTC for
    these system metadata timestamps with three fractional digits. Ordering of
    list results uses an internal monotonic sequence to keep creation order stable
    even when two creates land in the same millisecond.
    """
    return iso_millis(datetime.now(timezone.utc))


def iso_millis(dt):
    """ISO 8601 UTC with exactly three fractional digits and trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime string into a tz-aware UTC datetime.

    Returns None when the value is not a parseable datetime.
    """
    if not isinstance(value, str) or not value:
        return None
    raw = value.strip()
    try:
        s = raw
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None
