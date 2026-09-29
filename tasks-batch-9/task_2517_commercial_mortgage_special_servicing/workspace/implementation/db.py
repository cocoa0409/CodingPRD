"""In-memory data store.

Everything lives in plain dicts keyed by id.  The store is EMPTY on every
boot: no entity is ever seeded, preloaded or hardcoded.  Tests build all
state through the declared endpoints.
"""
import itertools
import uuid

from datetimes import parse_dt, wall_now_iso

# PRD section 2.5 — mandatory server startup default for the logical clock.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00.000Z"

COLLECTIONS = (
    "trusts",
    "loans",
    "transfer_events",
    "borrower_requests",
    "appraisals",
    "appraisal_reductions",
    "advances",
    "workout_plans",
    "workout_alternatives",
    "consultations",
    "reo_assets",
    "fee_accruals",
    "distribution_reports",
)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = parse_dt(CLOCK_STARTUP_DEFAULT)
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)

    def now(self):
        return self.clock


db = Store()


def new_id():
    return str(uuid.uuid4())


def base_row(with_common_fields=True):
    """Fresh identity block (PRD section 2.4)."""
    row = {"id": new_id(), "created_at": wall_now_iso()}
    if with_common_fields:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """Record a write against a row: refresh updated_at, bump version."""
    if row is None:
        return row
    if "version" in row:
        row["version"] = int(row["version"]) + 1
        row["updated_at"] = wall_now_iso()
    return row
