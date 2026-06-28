"""In-memory data store and logical clock.

PRD §2.5: the server-controlled logical clock starts at exactly
2026-01-01T00:00:00Z on every boot and never falls back to wall-clock time.

All storage is in-memory only (plain dicts keyed by id). Nothing is seeded at
startup: every entity is created by an API call. Per-test-server isolation
re-launches start.sh before each test, so state is naturally wiped each boot.
"""

import threading
import uuid
from datetime import datetime, timezone

# Counter used to make created_at strictly monotonic for stable ordering even
# when multiple rows are created within the same logical-clock instant.
_seq_lock = threading.Lock()
_seq = 0


def next_seq():
    global _seq
    with _seq_lock:
        _seq += 1
        return _seq


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = DEFAULT_CLOCK

    def get(self):
        return self.now

    def set(self, dt):
        self.now = dt


clock = Clock()


def iso_now():
    """ISO 8601 UTC timestamp with exactly three fractional digits.

    Used for created_at / updated_at, which track the *logical* clock so that
    rolling windows and TTLs are evaluated against the same time base.
    """
    return format_iso(clock.get())


def format_iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # millisecond precision, 'Z' suffix
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 timestamp (with or without 'Z'/offset) to aware UTC."""
    if s is None:
        return None
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse a YYYY-MM-DD date string into a date object."""
    return datetime.strptime(s, "%Y-%m-%d").date()


# ---------------------------------------------------------------------------
# Stores (one dict per entity, keyed by id)
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.accounts = {}
        self.rg_controls = {}
        self.geo_checks = {}
        self.events = {}
        self.markets = {}
        self.selections = {}
        self.bets = {}
        self.bet_legs = {}
        self.promotions = {}
        self.bonus_grants = {}
        self.ledger_entries = {}


db = Store()

# A single global lock serializes every mutating request so cascades stay atomic
# and the OCC checks behave deterministically (PRD §1: atomic cascades).
request_lock = threading.RLock()
