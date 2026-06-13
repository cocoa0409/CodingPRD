"""In-memory data store + logical clock.

All state lives in module-level dicts that are recreated when the process boots.
Nothing is seeded here — every entity is created by the API at runtime.
"""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # Each is a dict keyed by entity id.
        self.accounts = {}
        self.plans = {}
        self.locations = {}
        self.addons = {}
        self.vehicles = {}
        self.memberships = {}
        self.membership_addons = {}
        self.invoices = {}
        self.wash_events = {}
        self.wallet_transactions = {}
        self.freezes = {}
        # Logical clock: defaults to real wall clock until set via /_clock.
        self._clock = None
        # Monotonic insertion sequence: a stable tiebreak so "chronological by
        # created_at ascending" is deterministic even when the logical clock is
        # frozen and several rows share the same created_at (PRD 2.3, 2.9).
        self._seq = 0

    # ----- identity / time helpers -----
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        """Current logical clock (UTC). Driven by /_clock/set_current_utc."""
        if self._clock is not None:
            return self._clock
        return datetime.now(timezone.utc)

    def set_clock(self, dt):
        self._clock = dt


# Single global store. Recreated on every fresh process boot.
store = Store()


def iso_ms(dt):
    """Serialize a datetime to ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime, or None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
