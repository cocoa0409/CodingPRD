"""In-memory data store (PRD §2.4). All storage is plain Python dicts keyed by
id. The store starts completely EMPTY on every boot — no seeding, preloading,
or hardcoded entities. Every entity a test needs is built via the API surface.

A monotonically increasing sequence counter is kept so list endpoints can sort
by creation order (creation timestamp ascending, PRD §2.3) deterministically
even when two records are minted within the same millisecond.
"""


class DB:
    def __init__(self):
        self.tour_products = {}
        self.add_ons = {}
        self.vehicles = {}
        self.partner_venues = {}
        self.pickup_points = {}
        self.departures = {}
        self.stops = {}
        self.venue_confirmations = {}
        self.guests = {}
        self.bookings = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()
