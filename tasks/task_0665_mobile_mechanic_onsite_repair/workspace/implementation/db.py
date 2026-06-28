"""In-memory data store. All state is wiped on process restart.

No entity is seeded at startup; every record is created via the declared API.
"""
import uuid
from datetime import datetime, timezone

# Domain constants (SCAFFOLD constants block / PRD §3)
WARRANTY_WINDOW_DAYS = 30
CALLBACK_BUFFER_MINUTES = 30
CLOCK_DEFAULT_UTC = "2026-04-01T00:00:00Z"
ZONE_CODES = ["Z1", "Z2", "Z3", "Z4", "Z5", "Z6", "Z7", "Z8", "Z9"]

# Tiered parts markup constants
BAND_A_CAP_CENTS = 5000
BAND_B_CAP_CENTS = 20000
BAND_A_RATE = 0.45
BAND_B_RATE = 0.30
BAND_C_RATE = 0.18


class Store:
    """Holds all entity collections keyed by id, plus the logical clock."""

    def __init__(self):
        self.customers = {}
        self.fleet_accounts = {}
        self.mechanics = {}
        self.service_requests = {}
        self.quotes = {}
        self.job_visits = {}
        self.part_lines = {}
        self.catalog_parts = {}
        self.inspection_findings = {}
        self.payments = {}
        self.warranty_claims = {}
        # logical clock (datetime, UTC, tz-aware)
        self.clock = _parse_iso(CLOCK_DEFAULT_UTC)
        # monotonically-increasing sequence to break creation-time ties for sorting
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


def _parse_iso(s):
    """Parse an ISO-8601 instant into a tz-aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_iso(store):
    """Current logical-clock instant rendered ISO-8601 UTC with ms precision."""
    return iso_ms(store.clock)


def iso_ms(dt):
    """Render a datetime as ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


# Global singleton store. Re-created per fresh process (no persistence).
store = Store()
