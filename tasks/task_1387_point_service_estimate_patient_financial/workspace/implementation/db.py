"""In-memory data store. Starts EMPTY on every boot — no seeding whatsoever.

The logical clock starts at exactly 2026-08-01T00:00:00Z (PRD section 2.4);
the server never reads wall-clock time.
"""

import threading
from datetime import datetime, timezone


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        # entity tables: id -> record (plain dicts; keys starting with "_"
        # are internal and stripped at serialization)
        self.patients = {}
        self.charge_items = {}
        self.cpt_index = {}          # cpt_code -> charge item id
        self.payer_contracts = {}
        self.payer_code_index = {}   # payer_code -> contract id
        self.rates = {}
        self.snapshots = {}
        self.cases = {}
        self.estimates = {}
        self.authorizations = {}
        self.plans = {}
        self.deposits = {}
        self.variance_records = {}
        self.escalations = {}
        # counters
        self.seq = 0                 # global insertion-order counter (sort tiebreak)
        self.auth_seq = 0            # AUTH-<n> minter
        # logical clock (startup default per PRD 2.4)
        self.now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def next_seq(self):
        self.seq += 1
        return self.seq

    def mint_auth_number(self):
        self.auth_seq += 1
        return "AUTH-%d" % self.auth_seq


db = DB()
