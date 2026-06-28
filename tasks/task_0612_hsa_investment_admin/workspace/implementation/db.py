"""In-memory data store (PRD: no durable persistence; benchmark tests build all
state via the API surface). The store starts EMPTY on every boot — nothing is
seeded, preloaded, or hardcoded here.

Common fields (PRD §2.4): every resource carries an `id` (server-minted UUID,
no type prefix) and `created_at` (ISO 8601 UTC, 3 fractional digits, fixed at
creation). Most resources additionally carry `updated_at` and `version`
(integer starting at creation, +1 on each mutation). TaxForm is the sole
exception: only id + created_at.
"""
import uuid

from clock import clock


class Store:
    def __init__(self):
        # One dict per entity, keyed by id.
        self.accountholders = {}
        self.employers = {}
        self.payroll_periods = {}
        self.accounts = {}
        self.coverage_periods = {}
        self.contributions = {}
        self.investment_sweeps = {}
        self.distributions = {}
        self.receipts = {}
        self.debit_cards = {}
        self.excess_corrections = {}
        self.tax_forms = {}


db = Store()


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def now_iso():
    return clock.now_iso()


def stamp_create(obj, versioned=True):
    """Populate id / created_at (+ updated_at / version when versioned)."""
    obj["id"] = new_id()
    ts = now_iso()
    obj["created_at"] = ts
    if versioned:
        obj["updated_at"] = ts
        obj["version"] = 1
    return obj


def touch(obj):
    """Mark a mutation: refresh updated_at and increment version (PRD §2.4)."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj
