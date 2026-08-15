"""In-memory data store.

The store starts EMPTY on every boot — no seeding. Every entity a test
needs is constructed through the declared API surface. The process is
re-launched per test by the harness, so module-level state is per-test.
"""
import threading
import uuid


class Store:
    def __init__(self):
        self.terminals = {}
        self.products = {}
        self.customers = {}
        self.price_schedules = {}
        self.lifting_rights = {}
        self.supply_contracts = {}
        self.exchange_agreements = {}
        self.allocation_notices = {}
        self.lifting_tickets = {}
        self.bol_events = {}
        self.tax_rules = {}
        self.credit_hold_logs = {}
        # Monotonic creation counter — stable tie-break when created_at
        # timestamps coincide (the logical clock only moves on demand).
        self.seq = 0
        # BOL minting sequence per (terminal_id, yyyymmdd).
        self.bol_counters = {}


db = Store()

# Single process-wide lock so each HTTP request executes atomically.
lock = threading.RLock()


def next_seq():
    db.seq += 1
    return db.seq


def new_id():
    return str(uuid.uuid4())
