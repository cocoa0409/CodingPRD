"""In-memory data store plus the logical clock.

The store starts completely empty on every boot -- the implementation never seeds
entities at startup. Every record is created through the declared API surface.
"""
import threading

from util import CLOCK_DEFAULT


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # Logical clock: starts at exactly 2026-08-01T00:00:00Z and never falls
        # back to wall-clock time.
        self.clock = CLOCK_DEFAULT
        # Entity tables (insertion-ordered dicts keyed by id).
        self.clients = {}
        self.jurisdictions = {}
        self.jurisdiction_by_code = {}
        self.debtors = {}
        self.secured_parties = {}
        self.filing_requests = {}
        self.filings = {}
        self.lien_searches = {}
        self.hits = {}
        self.reports = {}
        self.events = {}


store = Store()


def now():
    """Current reading of the logical clock."""
    return store.clock
