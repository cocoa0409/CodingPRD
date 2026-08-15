"""In-memory data store. Starts empty on every boot — no seeding allowed.

Entity collections are keyed by id. A module-level `store` singleton holds
everything; `reset()` is never invoked from app startup — collections begin
empty by construction.
"""

import threading
import uuid
from datetime import datetime, timezone, date

_LOCK = threading.RLock()

# Logical clock: boots to exactly 2026-08-01T00:00:00Z
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.clock = DEFAULT_CLOCK
        self.payers = {}
        self.contracts = {}
        self.terms = {}
        self.carve_outs = {}
        self.stop_losses = {}
        self.escalators = {}
        self.amendments = {}
        self.network_agreements = {}
        self.claims = {}
        self.claim_lines = {}
        self.remittances = {}
        self.cases = {}
        self.appeals = {}
        self.proposals = {}
        self.alerts = {}
        # Monotonic creation sequence so created_at ties are broken deterministically
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()
lock = _LOCK


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    now = datetime.now(timezone.utc)
    ms = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return ms


def today():
    """UTC calendar-date part of the logical clock."""
    return store.clock.date()


def clock_iso():
    c = store.clock
    return c.strftime("%Y-%m-%dT%H:%M:%S.") + f"{c.microsecond // 1000:03d}Z"


def parse_date(s):
    """Parse a YYYY-MM-DD calendar date. Raises ValueError on bad input."""
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    if not isinstance(s, str):
        raise ValueError("date must be a string")
    if len(s) != 10 or s[4] != "-" or s[7] != "-":
        raise ValueError("date must be YYYY-MM-DD")
    y = int(s[0:4])
    m = int(s[5:7])
    d = int(s[8:10])
    return date(y, m, d)


def parse_clock(s):
    """Parse an ISO 8601 UTC datetime like 2026-08-01T00:00:00Z (fractional seconds allowed)."""
    if not isinstance(s, str):
        raise ValueError("datetime must be a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
