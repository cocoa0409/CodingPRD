"""In-memory data store. Empty on every boot; nothing is ever seeded."""
from datetime import datetime, timedelta

from util import UTC, new_id

# PRD 2.5: before the clock has ever been set it reads exactly this instant.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "trade_rules",
    "promotion_plans",
    "merchants",
    "licenses",
    "enrollments",
    "consumers",
    "applications",
    "loan_accounts",
    "projects",
    "milestones",
    "draws",
    "disputes",
    "alerts",
    "payments",
)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_EPOCH
        self._seq_counter = 0

    def next_seq(self):
        self._seq_counter += 1
        return self._seq_counter

    # ---- logical clock ----------------------------------------------------
    def now(self):
        return self.clock

    def today(self):
        return self.clock.date()

    # ---- record helpers ---------------------------------------------------
    def new_record(self, versioned=True):
        rec = {"id": new_id(), "created_at": self.clock, "_seq": self.next_seq()}
        if versioned:
            rec["updated_at"] = self.clock
            rec["version"] = 1
        return rec

    def touch(self, rec):
        """PRD 2.6: every mutation refreshes updated_at and bumps version."""
        rec["updated_at"] = self.clock
        rec["version"] = rec.get("version", 1) + 1
        return rec

    def ordered(self, collection):
        """PRD 2.3: list results are ordered by creation timestamp ascending."""
        return sorted(collection.values(), key=lambda r: (r["created_at"], r["_seq"]))


db = Store()


def days_after(instant, days):
    return instant + timedelta(days=days)
