"""In-memory data store. All dicts are keyed by entity id (UUID string).

The store starts empty on every boot. No seeding, no persistence, no
on-disk cache — the test harness restarts the process per test.
"""

from datetime import datetime, timezone


def _utcnow_iso():
    """Return current wall-clock UTC time as ISO8601 with 3 fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    """Holds every entity collection plus the logical clock."""

    def __init__(self):
        # Logical clock: fixed startup default 2026-08-01T00:00:00Z
        self.logical_clock = "2026-08-01T00:00:00.000Z"

        # Entity stores — all keyed by id
        self.properties = {}
        self.lease_spaces = {}
        self.tenants = {}
        self.leases = {}
        self.ti_projects = {}
        self.work_letters = {}
        self.plan_submissions = {}
        self.plan_review_comments = {}
        self.contractors = {}
        self.contractor_engagements = {}
        self.schedule_milestones = {}
        self.change_orders = {}
        self.disbursement_requests = {}
        self.lien_waivers = {}
        self.punch_items = {}
        self.overage_invoices = {}

    def clock_iso(self):
        return self.logical_clock

    def set_clock(self, iso):
        self.logical_clock = iso

    @staticmethod
    def now():
        """Server timestamp for created_at / updated_at — logical clock reading."""
        return _utcnow_iso()


# Module-level singleton (recreated per process boot)
store = Store()
