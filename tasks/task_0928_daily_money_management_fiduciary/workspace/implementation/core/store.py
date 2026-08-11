"""In-memory store.  Python dicts keyed by id; nothing touches disk.

The store starts completely empty on every boot: no entity is seeded,
preloaded, registered or hardcoded anywhere.  Every row the tests need is
created by the tests through the declared endpoints.
"""

import uuid

from .clock import parse_instant, render_date
from . import constants as K

COLLECTIONS = (
    "clients",
    "authorizations",
    "accounts",
    "payees",
    "budget_categories",
    "surety_bonds",
    "payments",
    "disputes",
    "reconciliation_periods",
    "statement_lines",
    "ledger_entries",
    "fraud_alerts",
    "benefit_applications",
    "family_recipients",
    "family_reports",
    "coordination_requests",
    "audit_entries",
)


class Store(object):
    def __init__(self):
        self.now = parse_instant(K.DEFAULT_CLOCK_UTC)
        self._seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    # -- identity ---------------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    # -- logical clock ----------------------------------------------------
    @property
    def today(self):
        return self.now.date()

    def today_str(self):
        return render_date(self.now.date())

    def current_month(self):
        return "{:04d}-{:02d}".format(self.now.year, self.now.month)

    # -- ordered access ---------------------------------------------------
    def ordered(self, collection):
        """PRD 2.3: created_at ascending, ties broken by write order."""
        rows = getattr(self, collection).values()
        return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


db = Store()


def new_row(collection, fields, versioned=True):
    """Create a row with the common properties of PRD section 2.5."""
    row = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "created_at": db.now,
    }
    if versioned:
        row["updated_at"] = db.now
        row["version"] = 1
    row.update(fields)
    getattr(db, collection)[row["id"]] = row
    return row


def bump(row):
    """Count the row as mutated: version +1 and updated_at refreshed."""
    row["version"] = row["version"] + 1
    row["updated_at"] = db.now
    return row


def all_of(collection):
    return list(getattr(db, collection).values())
