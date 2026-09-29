"""In-memory data store.

The store is empty on every boot: no entity is ever seeded, preloaded or
hardcoded.  Tests build every precondition through the declared API surface.
"""
import uuid


class Store:
    def __init__(self):
        self.projects = {}
        self.dams = {}
        self.sites = {}
        self.study_plans = {}
        self.studies = {}
        self.comments = {}
        self.parties = {}
        self.settlements = {}
        self.signatures = {}
        self.wqcs = {}
        self.measures = {}
        self.applications = {}
        self.orders = {}
        self.obligations = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def sorted_rows(collection, predicate=None):
    """Default list ordering: created_at ascending, insertion order as tie break."""
    rows = [r for r in collection.values() if predicate is None or predicate(r)]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows
