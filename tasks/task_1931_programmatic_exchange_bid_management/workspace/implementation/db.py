"""In-memory data store and the server-held logical clock.

The store starts empty on every boot — no seeding of any kind. Every entity
any caller needs is constructed through the declared API surface.

Time model (PRD §2.4): all temporal behavior is driven by a logical clock that
starts at exactly 2026-08-01T00:00:00Z and moves only via
POST /_clock/set_current_utc. It never falls back to wall-clock time.
"""

import threading
import uuid
from datetime import datetime, timezone


class Clock:
    """Logical clock. Startup default is exactly 2026-08-01T00:00:00Z."""

    def __init__(self):
        self._lock = threading.Lock()
        self._now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        with self._lock:
            return self._now

    def set(self, dt):
        with self._lock:
            self._now = dt
        return self._now


def parse_iso(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Raises ValueError for malformed strings, naive datetimes (no offset), and
    non-UTC offsets — PRD §2.8 stage 4 requires ISO 8601 UTC.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if not s:
        raise ValueError("empty")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError("naive datetime is not ISO 8601 UTC")
    if dt.utcoffset().total_seconds() != 0:
        raise ValueError("datetime offset is not UTC")
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits (created_at /
    updated_at / meta timestamps, PRD §2.2 and §2.6)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


def fmt_clock(dt):
    """Render a logical-clock-stamped instant the way the clock itself reads
    (PRD §2.4: the clock starts at exactly 2026-08-01T00:00:00Z). Fractional
    digits appear only when the stamped instant actually carries them, so an
    operator-supplied whole-second datetime echoes back verbatim."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        base += f".{dt.microsecond // 1000:03d}"
    return base + "Z"


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        self.clock = Clock()
        # global request lock: mutations and reads are serialized so a
        # multi-resource cascade can never interleave with another request
        self.lock = threading.RLock()
        # entity stores, keyed by id — all start empty
        self.publishers = {}
        self.partners = {}            # DemandPartner
        self.packages = {}            # InventoryPackage
        self.windows = {}             # SeasonalPricingWindow
        self.deals = {}               # Deal
        self.nodes = {}               # SupplyChainNode
        self.blocklist = {}           # BlocklistEntry
        self.records = {}             # AuctionRecord
        self.reports = {}             # ReconciliationReport
        self.payout_batches = {}      # PayoutBatch
        self.payout_lines = {}        # PayoutLine
        # monotonic arrival counter used to break created_at ties
        # deterministically (several records can share one logical timestamp)
        self._seq_lock = threading.Lock()
        self._seq = 0

    def next_seq(self):
        with self._seq_lock:
            self._seq += 1
            return self._seq

    def now(self):
        return self.clock.now()

    def now_str(self):
        return fmt_ts(self.clock.now())


store = Store()
