"""In-memory data store for the School Fundraising Booster API.

The store starts EMPTY on every process boot. No entity seeding occurs at
startup; every entity a test needs is constructed via the declared API surface.
"""

import uuid
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.campaigns = {}
        self.prize_tiers = {}
        self.sellers = {}
        self.products = {}
        self.orders = {}
        self.pledges = {}
        self.volunteers = {}
        self.shifts = {}
        self.disbursements = {}
        self._seq = 0
        # Monotonic sequential receipt-number generator (orders + pledges share
        # one sequence so receipts are globally ordered for settlement tiebreaks).
        self._receipt_seq = 0
        self._share_seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def next_receipt(self):
        self._receipt_seq += 1
        return self._receipt_seq

    def next_share_slug(self):
        self._share_seq += 1
        return "share_" + uuid.uuid4().hex


db = Store()
lock = threading.RLock()


def new_id():
    return str(uuid.uuid4())


def now_ts():
    """Creation/mutation wall-clock timestamp, ISO 8601 UTC with three fractional
    digits. This is the resource timestamp (created_at/updated_at), distinct from
    the logical business clock used for reconciled_at."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
