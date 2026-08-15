"""In-memory data store, logical clock (PRD §2.5), and version/timestamp bumping.

The store starts EMPTY on every boot — no seeding of any kind.
"""
import uuid
from datetime import datetime, timezone

from flask import g


class DB:
    def __init__(self):
        # Logical clock: fixed startup default; never falls back to wall clock.
        self.clock = datetime(2026, 8, 1, tzinfo=timezone.utc)
        self.seq = 0
        self.agencies = {}
        self.officers = {}
        self.reviewers = {}
        self.exams = {}
        self.items = {}
        self.submissions = {}
        self.meetings = {}
        self.findings = {}
        self.issues = {}
        self.plans = {}
        self.milestones = {}
        self.evidences = {}
        self.closures = {}
        self.reports = {}
        self.commitments = {}


db = DB()


def now():
    """Current logical time (server stamps come from the logical clock)."""
    return db.clock


def next_seq():
    db.seq += 1
    return db.seq


def new_id():
    return str(uuid.uuid4())


def touch(rec):
    """Mutation marker: version += 1 (if the entity carries a version) and
    updated_at refreshes (if carried). Deduped per request so that an entity
    affected through multiple legs of one cascade bumps exactly once
    (CommitmentLogEntry carries neither field and is never touched)."""
    try:
        seen = getattr(g, "_touched", None)
        if seen is None:
            seen = set()
            g._touched = seen
        if id(rec) in seen:
            return
        seen.add(id(rec))
    except RuntimeError:
        pass
    if "version" in rec:
        rec["version"] += 1
    if "updated_at" in rec:
        rec["updated_at"] = db.clock
