"""In-memory data store (PRD §2.4 common fields).

Every byte of state lives here in plain dicts keyed by id. Nothing is seeded at
startup — the store is empty on every boot. start.sh re-invocation starts a fresh
process, which constructs a fresh empty Store.

UUIDs are server-minted with no type prefix. created_at/updated_at are ISO 8601
UTC strings with three fractional digits. version is an integer starting at 1 and
incremented on every mutation. Payment is the lone resource WITHOUT updated_at/version.

NOTE on time: created_at/updated_at use the logical clock's wall-clock-free request
time? PRD §2.4 says created_at records when the resource was created. The logical
clock is described only for time-dependent COMPUTATIONS (SLA). Resource timestamps
use real UTC; SLA math uses the logical clock. We keep created_at monotonic per
process via a sequence counter for stable sort tie-breaks.
"""

import itertools
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.accounts = {}
        self.fee_schedules = {}
        self.transactions = {}
        self.document_items = {}
        self.fee_quotes = {}
        self.submissions = {}
        self.runner_trips = {}
        self.runner_legs = {}
        self.lien_packets = {}
        self.payments = {}
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_ts():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
