"""In-memory data store. Pure Python dicts keyed by id; a monotonic sequence
stabilizes created_at ordering; a logical clock (default 2026-08-01T00:00:00Z)
drives every server-stamped field and time-derived calculation.

The store starts EMPTY on every boot — no seeding anywhere.
"""
import threading
import uuid
from datetime import datetime, timezone

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock_now = DEFAULT_NOW
        self.seq = 0
        self.schools = {}
        self.students = {}
        self.staff = {}
        self.training_records = {}
        self.referrals = {}
        self.evaluations = {}
        self.plans = {}
        self.accommodations = {}
        self.acks = {}
        self.logs = {}
        self.reviews = {}
        self.testing_requests = {}
        self.consents = {}
        self.grievances = {}
        self.audit_events = {}


db = DB()


def now():
    return db.clock_now


def set_clock(value):
    db.clock_now = value


def next_seq():
    db.seq += 1
    return db.seq


def new_id():
    # PRD §2.4: "id — a server-minted UUID with no type prefix." Emit the
    # canonical hyphenated (RFC 4122) string form, not the 32-char hex form.
    return str(uuid.uuid4())


def create_record(coll, fields):
    """Insert a primary resource: id + created_at + updated_at + version=1."""
    ts = now()
    rec = {
        "id": new_id(),
        "_seq": next_seq(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    rec.update(fields)
    coll[rec["id"]] = rec
    return rec


def create_audit_event(fields):
    """Append to the audit ledger: only id + created_at (no updated_at/version)."""
    rec = {
        "id": new_id(),
        "_seq": next_seq(),
        "created_at": now(),
    }
    rec.update(fields)
    db.audit_events[rec["id"]] = rec
    return rec


def touch(rec):
    """A mutation of a resource: refresh updated_at, increment version by 1."""
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 1) + 1
