"""In-memory data store and the logical program clock.

The store starts completely empty on every boot; every entity is constructed
via the declared API surface. The logical clock starts at exactly
2026-08-01T00:00:00Z and never falls back to wall-clock time.
"""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.tenants = {}
        self.leases = {}
        self.sales_reports = {}
        self.settlements = {}
        self.payments = {}
        self.audits = {}
        self.reviews = {}
        self.draws = {}
        self.violations = {}
        self.waivers = {}
        self.enplanements = {}
        # Logical clock: startup default is exactly 2026-08-01T00:00:00Z.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Monotonic insertion counter used for creation-order list sorting.
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def now_iso():
    """Current logical-clock instant as ISO 8601 UTC with 3 fractional digits."""
    dt = db.clock
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '{0:03d}Z'.format(dt.microsecond // 1000)


def base_fields():
    """Common system-managed properties carried by every resource."""
    ts = now_iso()
    return {
        'id': new_id(),
        'created_at': ts,
        'updated_at': ts,
        'version': 1,
        '_seq': db.next_seq(),
    }
