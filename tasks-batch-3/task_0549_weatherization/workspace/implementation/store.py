"""In-memory data store for the Weatherization API.

All state lives in plain Python dicts keyed by id. The store is created fresh
when the process boots and is NEVER seeded/preloaded with any entity data --
tests construct every entity through the declared API surface. Because the test
harness relaunches the server before each test, a fresh process guarantees a
clean, empty store every time.
"""


class Store:
    def __init__(self):
        self.dwellings = {}
        self.wap_applications = {}
        self.jobs = {}
        self.audits = {}
        self.diagnostic_tests = {}
        self.scope_items = {}
        self.crews = {}
        self.crew_assignments = {}
        self.rebate_claims = {}
        self.financing_plans = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


# Single process-wide store instance. No entities are inserted here at import
# time -- it starts empty on every boot.
db = Store()
