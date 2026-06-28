"""In-memory data store (PRD §2.4).

All storage is in-memory only — Python dicts keyed by id. The store starts EMPTY
on every boot; nothing is seeded or preloaded. Each `start.sh` re-invocation
launches a fresh process, wiping all state.

Common fields (PRD §2.4):
  - id          : server-minted UUID, no type prefix
  - created_at  : ISO 8601 UTC instant, three fractional digits
  - updated_at  : refreshed on every mutation (absent on BenefitScheduleItem)
  - version     : starts at 1 on creation, +1 on every mutation
                  (absent on BenefitScheduleItem)

BenefitScheduleItem is immutable: only id + created_at, no updated_at/version.
"""

import uuid
import threading

from clock import clock, format_iso8601_ms


class Store:
    """A single collection keyed by id, preserving insertion order."""

    def __init__(self, name, versioned=True):
        self.name = name
        self.versioned = versioned
        self.items = {}  # id -> record dict
        self._seq = 0    # monotonic insertion counter for stable sort

    def insert(self, record, with_version=True):
        rid = str(uuid.uuid4())
        now = _now_iso()
        record["id"] = rid
        record["created_at"] = now
        if with_version and self.versioned:
            record["updated_at"] = now
            record["version"] = 1
        record["_seq"] = self._next_seq()
        self.items[rid] = record
        return record

    def _next_seq(self):
        self._seq += 1
        return self._seq

    def get(self, rid):
        return self.items.get(rid)

    def all(self):
        # Sorted by creation order (created_at ascending; _seq breaks ties).
        return sorted(self.items.values(), key=lambda r: r["_seq"])

    def touch(self, record):
        """Mutation bookkeeping: refresh updated_at and bump version (PRD §2.4)."""
        if self.versioned and "version" in record:
            record["updated_at"] = _now_iso()
            record["version"] = record.get("version", 1) + 1


def _now_iso():
    """created_at/updated_at use ISO 8601 UTC with three fractional digits.

    These resource timestamps are minted from the logical clock so that
    creation-order and time-sensitive comparisons stay deterministic under the
    server-controlled clock (PRD §2.4 / §2.5).
    """
    return format_iso8601_ms(clock.now())


class DB:
    """Container of all collections + a global lock for atomic operations."""

    def __init__(self):
        self.lock = threading.RLock()
        self.employers = Store("employers")
        self.plan_products = Store("plan_products")
        self.schedule_items = Store("schedule_items", versioned=False)
        self.enrollment_periods = Store("enrollment_periods")
        self.employees = Store("employees")
        self.disbursement_accounts = Store("disbursement_accounts")
        self.enrollments = Store("enrollments")
        self.payroll_deductions = Store("payroll_deductions")
        self.claims = Store("claims")
        self.disbursements = Store("disbursements")
        self.portability_conversions = Store("portability_conversions")
        self.section125_elections = Store("section125_elections")


db = DB()
