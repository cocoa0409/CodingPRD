"""In-memory data store for the Backline Tour Rental API.

All state lives in plain Python dicts keyed by id. The store starts completely
empty on every boot — the implementation never seeds, preloads, or hardcodes
any entity. The logical clock defaults to exactly 2026-08-01T00:00:00Z per
PRD §2.5 and never falls back to wall-clock time.
"""

import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # Entity tables, keyed by id (UUID string, no type prefix)
        self.artists = {}
        self.tours = {}
        self.tour_stops = {}
        self.rider_lines = {}
        self.gear_models = {}
        self.gear_units = {}
        self.reservation_lines = {}
        self.shipments = {}
        self.shipment_lines = {}
        self.flight_cases = {}
        self.partner_vendors = {}
        self.cross_rental_requests = {}
        self.maintenance_tickets = {}
        self.damage_claims = {}
        # Logical clock: defaults to exactly 2026-08-01T00:00:00Z per PRD §2.5.
        # Never falls back to wall-clock time.
        self.current_utc = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()


def new_id():
    """Mint a UUID identifier with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def now_iso():
    """Return the logical-clock time as an ISO 8601 UTC string with three
    fractional digits (PRD §2.2 / §2.4)."""
    dt = store.current_utc
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms
