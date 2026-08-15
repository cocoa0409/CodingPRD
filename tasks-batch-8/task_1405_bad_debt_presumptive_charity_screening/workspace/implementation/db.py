"""In-memory data store. Starts EMPTY on every boot — no seeding whatsoever.

The logical clock starts at exactly 2026-08-01T00:00:00Z (PRD section 2.4);
the server never falls back to wall-clock time.
"""

import threading
from datetime import datetime, timezone


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        # entity tables: id -> record (plain dicts; keys starting with "_"
        # are internal and stripped at serialization)
        self.accounts = {}              # SelfPayAccount
        self.statements = {}            # Statement
        self.screenings = {}            # PresumptiveCharityScreening
        self.early_out_placements = {}  # EarlyOutPlacement
        self.agency_placements = {}     # CollectionAgencyPlacement
        self.disputes = {}              # PatientDispute
        self.payment_plans = {}         # PaymentPlan
        self.write_offs = {}            # BadDebtWriteOff
        self.medicare_log_entries = {}  # MedicareBadDebtLogEntry (append-only)
        self.recovery_transactions = {}  # RecoveryTransaction
        self.vendor_snapshots = {}      # VendorPerformanceSnapshot (append-only)
        # global insertion-order counter (stable sort tiebreak)
        self.seq = 0
        # logical clock (startup default per PRD 2.4)
        self.now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def next_seq(self):
        self.seq += 1
        return self.seq


db = DB()
