"""In-memory data store. Empty on every boot; tests build all state via the API.

Each entity collection is an ordered dict keyed by id (insertion order == creation
order, used for ascending creation-time list sorts). A monotonic sequence counter
disambiguates timestamps that may collide at millisecond resolution.
"""


class DB:
    def __init__(self):
        self.pricing_policies = {}
        self.customers = {}
        self.crews = {}
        self.trucks = {}
        self.haul_jobs = {}
        self.job_items = {}
        self.photo_estimates = {}
        self.dispatches = {}
        self.diversion_records = {}
        self.dump_tickets = {}
        self.invoices = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()
