"""In-memory data store. Every byte of state lives here and is wiped on each
fresh process boot. No seeding, no preload, no persistence."""

import uuid
import threading
from datetime import datetime, timezone


# A single global lock to keep multi-step mutations atomic under Flask's
# threaded server.
LOCK = threading.RLock()


# One dict per entity collection, keyed by id.
funds = {}
criteria = {}
applicants = {}
applications = {}
recommendations = {}
transcripts = {}
committee_members = {}
committee_assignments = {}
rubric_scores = {}
awards = {}
disbursements = {}
renewal_reviews = {}
stewardship_records = {}

# Monotonic counter to break created_at ties deterministically (creation order).
_seq = 0


def reset():
    """Used only for completeness; the process boots empty anyway."""
    global _seq
    funds.clear()
    criteria.clear()
    applicants.clear()
    applications.clear()
    recommendations.clear()
    transcripts.clear()
    committee_members.clear()
    committee_assignments.clear()
    rubric_scores.clear()
    awards.clear()
    disbursements.clear()
    renewal_reviews.clear()
    stewardship_records.clear()
    _seq = 0


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC with exactly three fractional digits (milliseconds)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def next_seq():
    global _seq
    _seq += 1
    return _seq


def common_create(record):
    """Attach the standard system-managed fields (id, created_at, updated_at,
    version) plus an internal creation-order sequence."""
    record["id"] = new_id()
    ts = now_iso()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def upload_create(record):
    """Immutable upload record: id + created_at only (Recommendation, Transcript)."""
    record["id"] = new_id()
    record["created_at"] = now_iso()
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Bump updated_at and version on a mutation."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
