"""In-memory data store. All state lives in module-level dicts keyed by id.

Every byte of state is wiped on each process start because these dicts are
re-initialized when the module is imported by a fresh `python3 app.py`.
NOTHING is seeded here — the store starts empty; tests build all preconditions
via the declared API surface.
"""
import uuid
from datetime import datetime, timezone

from response import now_iso

# Resource tables, keyed by id
providers = {}
elections = {}
benefit_periods = {}
certifications = {}
care_plans = {}
care_days = {}
coverage_items = {}
physicians = {}
bereavement_cases = {}

# Monotonic creation sequence — provides a deterministic created_at tie-break
# (created_at strings have only millisecond precision, which can collide).
_create_seq = 0

# The server's logical "current UTC" clock, driven by POST /_clock/set_current_utc.
# Defaults to real wall-clock now until a test sets it.
_clock = {"current_utc": datetime.now(timezone.utc)}


def new_id():
    return str(uuid.uuid4())


def next_seq():
    global _create_seq
    _create_seq += 1
    return _create_seq


def base_fields():
    """Common system fields stamped at creation: created_at, updated_at, version,
    plus an internal _seq for deterministic ordering."""
    ts = now_iso()
    return {
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(record):
    """Refresh updated_at and bump version on every mutation (PRD §2.4)."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1


def get_clock():
    return _clock["current_utc"]


def set_clock(dt):
    _clock["current_utc"] = dt
