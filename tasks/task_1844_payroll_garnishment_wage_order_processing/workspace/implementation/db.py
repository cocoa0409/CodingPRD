"""In-memory data store.

Everything lives in module-level dicts keyed by id. Nothing is persisted to
disk, so a fresh process boot (per-test-server isolation) starts empty. The
store MUST NOT be seeded: every entity is built through the declared API.
"""

from datetime import datetime


class Store:
    def __init__(self):
        # The logical clock. Startup default is exactly 2026-08-01T00:00:00Z
        # and it never falls back to wall-clock time.
        self.clock = datetime(2026, 8, 1, 0, 0, 0)
        # Global monotonic sequence: stable tie-break wherever created_at /
        # received_at timestamps tie (never the record id).
        self.seq = 0

        self.employers = {}       # id -> Employer
        self.employees = {}       # id -> Employee
        self.runs = {}            # id -> PayrollRun
        self.statements = {}      # id -> PayStatement
        self.authorities = {}     # id -> IssuingAuthority
        self.orders = {}          # id -> GarnishmentOrder
        self.state_rules = {}     # state_code -> StateRule
        self.events = {}          # id -> WithholdingEvent
        self.remittances = {}     # id -> Remittance
        self.audit_entries = {}   # id -> AuditLogEntry

        # Segregation of duties: run_id -> X-User-ID that paid the run.
        self.run_payers = {}


store = Store()


def next_seq():
    store.seq += 1
    return store.seq


def logical_now():
    return store.clock
