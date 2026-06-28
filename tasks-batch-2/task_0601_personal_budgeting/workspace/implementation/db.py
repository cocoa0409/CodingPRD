"""In-memory data store for the Personal Budgeting API.

The store starts EMPTY on every process boot. No entity seeding occurs at
startup; every entity a test needs is constructed via the declared API surface.
"""

import uuid
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.households = {}
        self.members = {}
        self.accounts = {}
        self.transactions = {}
        self.category_rules = {}
        self.budget_periods = {}
        self.budget_categories = {}
        self.goals = {}
        self.goal_contributions = {}
        self.recurring_bills = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
lock = threading.RLock()


def new_id():
    return str(uuid.uuid4())


def now_ts():
    """Creation/mutation wall-clock timestamp, ISO 8601 UTC with three fractional
    digits. This is the resource timestamp (created_at/updated_at), distinct from
    the logical business clock used for forecast dating."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
