"""In-memory data store. Wiped on every process boot (no persistence).

The store starts EMPTY. No entity is seeded/preloaded; every entity is built by
tests via the declared API surface.
"""
import uuid
import itertools
from datetime import datetime, timezone


def _wall_now_iso():
    """Server wall-clock ISO 8601 UTC with three fractional digits.

    Used for created_at / updated_at / api_request_timestamp (PRD §2.2, §2.4).
    The logical clock (clock.py) governs completed_at + session windows only.
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


class Store:
    """One dict per entity-type, keyed by id. A monotonic creation counter gives
    a stable creation order for default sorting & tie-breaks."""

    def __init__(self):
        self.license_programs = {}
        self.question_items = {}
        self.subscription_plans = {}
        self.ce_bundles = {}
        self.cohorts = {}
        self.cohort_sessions = {}
        self.learners = {}
        self.enrollments = {}
        self.installments = {}
        self.study_plan_domains = {}
        self.practice_sessions = {}
        self.mock_exams = {}
        self.pass_guarantee_claims = {}
        self.ce_credit_awards = {}
        self.cohort_memberships = {}
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def reset_store():
    global db
    db = Store()


def stamp_create(rec, with_version=True):
    """Set id, created_at, and (unless suppressed) updated_at/version.

    A monotonic _seq preserves creation order for default sorting and tie-breaks.
    """
    now = _wall_now_iso()
    rec["id"] = new_id()
    rec["created_at"] = now
    rec["_seq"] = db.next_seq()
    if with_version:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    """Mutation: refresh updated_at, increment version (PRD §2.4)."""
    rec["updated_at"] = _wall_now_iso()
    rec["version"] = rec.get("version", 1) + 1
