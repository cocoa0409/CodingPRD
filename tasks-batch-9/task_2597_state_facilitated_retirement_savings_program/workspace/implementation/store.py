"""In-memory data store and the logical clock.

Storage is process-local Python dictionaries only.  The store always starts
completely EMPTY: no entity is ever seeded, preloaded or hardcoded at import
or startup time.  Tests build every precondition through the public API.
"""
from datetime import datetime

from util import fmt_instant, new_id

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, 0)

COLLECTIONS = (
    "program_years",
    "investment_options",
    "employers",
    "exemption_certifications",
    "participants",
    "enrollments",
    "participant_accounts",
    "investment_elections",
    "payroll_remittances",
    "remittance_lines",
    "excess_cases",
    "penalty_assessments",
    "enforcement_referrals",
    "portability_transfers",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0
        # The logical clock: never wall-clock time.
        self.clock = CLOCK_EPOCH

    # -------------------------------------------------------------- clock
    def now(self):
        return self.clock

    def now_iso(self):
        return fmt_instant(self.clock)

    def today(self):
        return self.clock.date()

    def year(self):
        return self.clock.year

    def set_clock(self, dt):
        self.clock = dt

    # ------------------------------------------------------------ helpers
    def next_seq(self):
        self._seq += 1
        return self._seq

    def insert(self, collection, row, versioned=True):
        row["id"] = row.get("id") or new_id()
        row["created_at"] = self.now_iso()
        if versioned:
            row["updated_at"] = row["created_at"]
            row["version"] = 1
        row["_seq"] = self.next_seq()
        getattr(self, collection)[row["id"]] = row
        return row

    def touch(self, row):
        """Refresh updated_at and advance version by exactly one."""
        if row is None:
            return None
        row["updated_at"] = self.now_iso()
        row["version"] = int(row.get("version", 1)) + 1
        return row

    def ordered(self, collection):
        """Every row of a collection in created_at ascending order (stable by insertion)."""
        rows = list(getattr(self, collection).values())
        rows.sort(key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))
        return rows


db = Store()
