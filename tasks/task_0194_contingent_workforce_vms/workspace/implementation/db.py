"""In-memory data store. All state lives in module-level dicts keyed by id.

The store starts EMPTY on every process boot. Nothing is seeded here.
"""
import uuid
from datetime import datetime, timezone

# Each is a dict: id -> record (a plain dict).
programs = {}
suppliers = {}
workers = {}
requisitions = {}
distributions = {}
submittals = {}
assignments = {}
statements_of_work = {}
milestones = {}
timesheets = {}
expenses = {}

# Monotonic sequence to break created_at ties deterministically.
_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())


def now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def common_fields():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(record):
    """Mark a record as mutated: bump version and updated_at."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
