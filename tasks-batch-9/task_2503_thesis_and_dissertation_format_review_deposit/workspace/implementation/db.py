"""In-memory data store.

Every collection starts EMPTY on boot. No entity is ever seeded, preloaded or
hardcoded here; tests build all preconditions through the declared API surface.
"""

import uuid

from logical_clock import clock


class Store:
    def __init__(self):
        self.terms = {}
        self.students = {}
        self.faculty_members = {}
        self.defense_rooms = {}
        self.theses = {}
        self.committees = {}
        self.committee_members = {}
        self.defense_events = {}
        self.format_reviews = {}
        self.embargo_requests = {}
        self.permission_records = {}
        self.integrity_screenings = {}
        self.repository_deposits = {}
        self.graduation_clearances = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_row(**fields):
    """Create a row carrying the four common properties (PRD section 2.4)."""
    now = clock.now()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    row.update(fields)
    return row


def touch(row):
    row["updated_at"] = clock.now()
    row["version"] = row["version"] + 1


def write(row, **fields):
    """Direct mutation: always refreshes updated_at and bumps version by one."""
    for key, value in fields.items():
        row[key] = value
    touch(row)
    return row


def reconcile(row, **fields):
    """Derived/cascaded mutation: only bumps version when a value truly changed."""
    changed = False
    for key, value in fields.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


def by_created_at(rows):
    """Ascending created_at, ties broken by insertion sequence."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def by_created_at_version_asc(rows):
    """Ascending created_at, ties broken by version ASC."""
    return sorted(rows, key=lambda r: (r["created_at"], r["version"], r["_seq"]))


def newest_by_created_at_version_desc(rows):
    """Greatest created_at, ties broken by version DESC."""
    if not rows:
        return None
    return max(rows, key=lambda r: (r["created_at"], r["version"], r["_seq"]))
