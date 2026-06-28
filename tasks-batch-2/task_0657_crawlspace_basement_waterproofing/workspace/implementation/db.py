"""In-memory data store.

All state lives in module-level dicts keyed by UUID id. The store starts
completely empty on every boot — NO entity is seeded, preloaded, or hardcoded.
Tests build all state through the declared API surface.

Timestamps are formatted as ISO 8601 UTC with three fractional digits, derived
from the logical clock (clock.py) so that created_at/updated_at track logical
time, matching the time-dependent rules in PRD §2.5.
"""
import uuid

from clock import clock


class Store:
    """A keyed collection of one entity type plus an insertion sequence counter."""

    def __init__(self):
        self.items = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


# One store per entity type. All empty at boot.
homeowners = Store()
jobs = Store()
inspections = Store()
quotes = Store()
financing_applications = Store()
install_orders = Store()
crew_bookings = Store()
crews = Store()
warranties = Store()
service_visits = Store()
claims = Store()
foundation_referrals = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Current logical clock as ISO 8601 UTC with three fractional digits."""
    dt = clock.now()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def reset_all():
    """Wipe every store. Used only for completeness; a fresh process boot already
    yields empty stores."""
    for store in (
        homeowners, jobs, inspections, quotes, financing_applications,
        install_orders, crew_bookings, crews, warranties, service_visits,
        claims, foundation_referrals,
    ):
        store.items.clear()
        store._seq = 0
    clock.reset()
