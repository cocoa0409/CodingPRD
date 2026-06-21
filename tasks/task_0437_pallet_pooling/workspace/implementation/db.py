"""In-memory data store (PRD §2.4 common properties + §2.4 logical clock).

All state is held in module-level dicts keyed by id. A fresh process boot (every
per-test server restart) starts the store empty: NO entity is ever seeded or
preloaded. The logical clock defaults to 2026-01-01T00:00:00Z on boot.
"""
import uuid
from datetime import datetime, timezone

# Logical clock default (PRD §2.4): exactly 2026-01-01T00:00:00Z on startup.
CLOCK_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        # One dict per entity, keyed by id.
        self.pool_policies = {}
        self.asset_types = {}
        self.accounts = {}
        self.locations = {}
        self.assets = {}
        self.transfer_orders = {}
        self.hires = {}
        self.audits = {}
        self.vouchers = {}
        self.collection_requests = {}
        self.repair_jobs = {}
        self.invoices = {}
        self.invoice_lines = {}
        self.demand_forecasts = {}
        # Logical clock (PRD §2.4).
        self.clock = CLOCK_DEFAULT
        # Monotonic creation sequence to give a stable secondary sort that is
        # robust even when several entities are created within the same instant.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def iso_clock(self):
        """The current logical clock formatted as an ISO 8601 UTC string."""
        return iso(self.clock)


db = Store()


def new_id():
    """UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def now_iso():
    """Server wall-clock instant, ISO 8601 UTC with three fractional digits.

    Used for created_at / updated_at and the response envelope timestamp
    (PRD §2.2, §2.4). This is distinct from the logical clock.
    """
    return iso(datetime.now(timezone.utc))


def iso(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 instant into an aware UTC datetime.

    Returns None if the value is not a parseable datetime string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
