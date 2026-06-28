"""In-memory data store. Every dict is keyed by entity id.

The store starts EMPTY on every boot. No seeding, no preloaded entities.
A monotonically-increasing sequence stamps a creation order onto every record so
that list endpoints can sort by creation timestamp ascending (PRD §2.3) without
tie ambiguity when two records share the same millisecond.
"""


class DB:
    def __init__(self):
        self.councils = {}
        self.troops = {}
        self.members = {}
        self.dues_invoices = {}
        self.payments = {}
        self.leader_credentials = {}
        self.advancements = {}
        self.events = {}
        self.event_registrations = {}
        self.fundraisers = {}
        self.fundraiser_orders = {}
        self.booth_reservations = {}
        self.fund_ledger_entries = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()
