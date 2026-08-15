"""In-memory data store. Starts empty on every boot; no seeding.

The per-test-server harness restarts the process before every test, so
module-level state here is naturally fresh per test.
"""


class DB:
    def __init__(self):
        self.merchants = {}
        self.rules = {}
        self.transactions = {}
        self.chargebacks = {}
        self.evidence_items = {}
        self.representments = {}
        self.fee_assessments = {}
        self.reserve_accounts = {}
        self.ledger_entries = {}
        self.ratio_snapshots = {}
        self.program_enrollments = {}
        self.remediation_plans = {}
        self.prevention_alerts = {}
        self.education_assignments = {}


db = DB()
