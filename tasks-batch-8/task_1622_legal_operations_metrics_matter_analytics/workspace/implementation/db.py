"""In-memory data store. Starts completely empty on every boot — no seeding."""
import itertools
import threading
import uuid

from clock import CLOCK


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = itertools.count(1)
        self.departments = {}
        self.fiscal_periods = {}
        self.practice_areas = {}
        self.matter_types = {}
        self.firms = {}
        self.counsel = {}
        self.matters = {}
        self.assignments = {}
        self.budgets = {}
        self.accruals = {}
        self.invoices = {}
        self.spend_lines = {}
        self.dashboards = {}

    def next_seq(self):
        return next(self.seq)


store = Store()


def new_entity(fields):
    """Create a common-fields entity: id, created_at, updated_at, version."""
    now = CLOCK.iso_ms()
    e = {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    e.update(fields)
    return e


def new_ledger_entry(fields):
    """Spend lines carry only id + created_at (no updated_at / version)."""
    e = {
        "id": str(uuid.uuid4()),
        "created_at": CLOCK.iso_ms(),
        "_seq": store.next_seq(),
    }
    e.update(fields)
    return e


def touch(e):
    """Register a mutation: refresh updated_at and bump version by exactly one."""
    e["updated_at"] = CLOCK.iso_ms()
    e["version"] += 1
