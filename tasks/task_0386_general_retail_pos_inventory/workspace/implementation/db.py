"""In-memory data store. Everything is wiped on every process start.

No entity is ever seeded, preloaded, or hardcoded — tests build all state
through the declared API surface.
"""
import itertools
import threading
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_iso():
    # Wall-clock timestamp for created_at/updated_at (PRD §2.4): ISO 8601 UTC,
    # three fractional digits. Distinct from the logical clock used by layaway
    # due-date sweeps (PRD §3.12), which is held in Store.LOGICAL_CLOCK.
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    """The whole in-memory state of the server."""

    def __init__(self):
        self.lock = threading.RLock()
        # entity collections keyed by id
        self.stores = {}
        self.products = {}
        self.inventory_items = {}
        self.loyalty_accounts = {}
        self.promotions = {}
        self.cash_sessions = {}
        self.sales = {}
        self.tender_lines = {}
        self.layaways = {}
        self.transfers = {}
        self.count_sheets = {}
        # monotonic counter to preserve creation order deterministically
        self._seq = itertools.count(1)
        # logical clock (PRD §3.12); None until the first advance
        self.logical_clock = None

    def next_seq(self):
        return next(self._seq)


DB = Store()
