"""In-memory data store, logical clock, id/sequence management.

The store starts completely empty on every boot. No seeding of any kind.
"""
import itertools
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_START_CLOCK = "2026-05-01T00:00:00Z"


def _parse_start(value):
    return datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.clock = _parse_start(_START_CLOCK)
        self.seq = itertools.count(1)          # global insertion order counter
        self.policy_number_seq = itertools.count(1)

        self.insured_persons = {}
        self.product_templates = {}
        self.applications = {}
        self.policies = {}
        self.billing_cycles = {}
        self.loans = {}
        self.loan_accruals = {}
        self.dividend_declarations = {}
        self.nonforfeiture_elections = {}
        self.reinstatement_requests = {}
        self.riders = {}
        self.conversion_requests = {}
        self.ledger_entries = {}

    # -- id / ordering helpers ------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self.seq)

    def next_policy_number(self):
        return "%08d" % next(self.policy_number_seq)

    # -- clock ----------------------------------------------------------------
    def current_datetime(self):
        return self.clock

    def current_date(self):
        return self.clock.date()

    def set_clock(self, dt):
        self.clock = dt


store = Store()
