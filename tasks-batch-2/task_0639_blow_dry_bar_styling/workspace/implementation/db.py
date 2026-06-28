"""In-memory data store. Everything is wiped on each process start — no
seeding, no preloading, no disk persistence."""

import uuid
from datetime import datetime, timezone


class DB:
    def __init__(self):
        # One dict per entity, keyed by id.
        self.style_services = {}
        self.add_ons = {}
        self.membership_plans = {}
        self.members = {}
        self.stylists = {}
        self.chairs = {}
        self.appointments = {}
        self.appointment_add_ons = {}
        self.event_blocks = {}
        self.products = {}
        self.retail_sales = {}
        self.package_purchases = {}

        # Ledgers / auxiliary append-only logs (computed-field reconciliation).
        # prepay top-ups: list of {member_id, amount_cents}
        self.prepay_topups = []

        # Logical clock. Default at startup is 2026-01-01T00:00:00Z.
        self.clock_utc = "2026-01-01T00:00:00.000Z"
        self.current_minute = 0  # minutes-from-midnight UTC of the set instant


db = DB()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
