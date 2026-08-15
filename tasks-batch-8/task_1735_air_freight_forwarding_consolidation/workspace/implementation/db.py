"""In-memory data store and the logical clock.

The store starts byte-empty on every boot: no seeding, no persistence.
All records are plain Rec instances held in module-level dicts keyed by id.
The logical clock starts at exactly 2026-08-01T00:00:00Z (PRD §2.9) and is
the only time source for created_at/updated_at and every time-driven rule.
"""
from datetime import datetime, timezone


class Rec:
    """Attribute-access record."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __repr__(self):  # pragma: no cover
        return f"Rec({self.__dict__!r})"


class Store:
    def __init__(self):
        # entity tables: id -> Rec
        self.shippers = {}
        self.bookings = {}
        self.mawbs = {}
        self.hwbs = {}
        self.screenings = {}
        self.customs_entries = {}
        self.rate_agreements = {}
        self.milestones = {}
        self.claims = {}
        # uniqueness indexes for business identifiers
        self.shipper_by_account_code = {}
        self.hwb_by_number = {}
        self.mawb_by_number = {}
        # monotonic creation sequence for deterministic ordering / latest-record
        # resolution (screening clearance judges the latest record per type)
        self.seq = 0
        # logical clock: fixed startup default per PRD §2.9, never wall-clock
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        # last issued created_at: record creation timestamps never go backward,
        # so creation order is always recoverable from created_at alone
        # (PRD §3.3 requires strictly increasing created_at within one submit).
        self.last_issued = None

    def next_seq(self):
        self.seq += 1
        return self.seq

    def now(self):
        return self.clock

    def set_clock(self, dt):
        self.clock = dt

    def issue_ts(self):
        """Mint a creation timestamp: the logical clock, but strictly after the
        previously issued timestamp (1 ms step) so created_at ordering always
        matches creation order even when the clock does not advance."""
        from datetime import timedelta
        ts = self.clock
        if self.last_issued is not None and ts <= self.last_issued:
            ts = self.last_issued + timedelta(milliseconds=1)
        self.last_issued = ts
        return ts


store = Store()
