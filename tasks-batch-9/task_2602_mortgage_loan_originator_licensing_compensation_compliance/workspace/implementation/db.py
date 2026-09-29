"""In-memory data store. Starts completely empty on every boot — nothing is
seeded, preloaded or hardcoded. Tests build all state through the API."""
import threading
from datetime import datetime, timezone

from flask import g

from util import new_id

# Startup default for the logical clock, per PRD 2.4.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

lock = threading.RLock()


class Store(object):
    def __init__(self):
        self.originators = {}
        self.license_registrations = {}
        self.sponsorship_transfers = {}
        self.ce_courses = {}
        self.ce_credits = {}
        self.compensation_plans = {}
        self.compensation_variables = {}
        self.loan_applications = {}
        self.pricing_exceptions = {}
        self.compensation_records = {}
        self.advertisements = {}
        self.examination_inquiries = {}
        self.investigations = {}
        self.audit_events = {}
        self.clock = CLOCK_DEFAULT
        self._insert_seq = 0
        self._audit_seq = 0

    def next_insert_seq(self):
        self._insert_seq += 1
        return self._insert_seq

    def next_audit_seq(self):
        self._audit_seq += 1
        return self._audit_seq


db = Store()


def now():
    """The logical clock. Nothing in the business logic reads the wall clock."""
    return db.clock


def _touched():
    try:
        s = g._touched
    except (AttributeError, RuntimeError):
        s = set()
        try:
            g._touched = s
        except RuntimeError:
            pass
    return s


def create(collection, data):
    """Insert a row with the common system fields stamped from the clock."""
    row = {
        "id": new_id(),
        "created_at": db.clock,
        "updated_at": db.clock,
        "version": 1,
        "_seq": db.next_insert_seq(),
    }
    row.update(data)
    collection[row["id"]] = row
    # A row created in this request is never additionally version-bumped by it.
    _touched().add(row["id"])
    return row


def touch(row):
    """Refresh updated_at and increment version — at most once per row per
    request, so a multi-hop cascade that revisits a row still moves it by 1."""
    if row is None:
        return row
    marks = _touched()
    if row["id"] in marks:
        return row
    marks.add(row["id"])
    row["updated_at"] = db.clock
    row["version"] = row.get("version", 1) + 1
    return row


def sort_key(row):
    """Default list ordering: created_at ASC, insertion order as tie-break."""
    return (row["created_at"], row["_seq"])
