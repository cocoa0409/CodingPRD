"""In-memory data store and the logical clock.

The store starts EMPTY on every boot: nothing is seeded, preloaded or hardcoded.
Every entity is created through the declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_seq_counter = itertools.count(1)


class _Store(object):
    def __init__(self):
        self.clock = CLOCK_EPOCH
        self.clients = {}
        self.sites = {}
        self.contractors = {}
        self.prequalifications = {}
        self.safety_statistics = {}
        self.written_programs = {}
        self.improvement_plans = {}
        self.insurance_certificates = {}
        self.workers = {}
        self.worker_qualifications = {}
        self.site_access_grants = {}
        self.incident_reports = {}
        self.variances = {}
        self.subcontractor_links = {}


S = _Store()


def now():
    """The logical clock -- the wall clock is never read."""
    return S.clock


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def base_row(versioned=True):
    row = {"id": new_id(), "_seq": next_seq(), "created_at": now()}
    if versioned:
        row["updated_at"] = now()
        row["version"] = 1
    return row


def touch(row):
    """Advance a row's own version and refresh its own updated_at."""
    if "version" in row:
        row["version"] = row["version"] + 1
        row["updated_at"] = now()
    return row


def insert(table, row):
    table[row["id"]] = row
    return row


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])


def sort_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def sort_created_id(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["id"]))
