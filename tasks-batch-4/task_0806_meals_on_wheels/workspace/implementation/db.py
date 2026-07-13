"""In-memory data store. Fresh (empty) on every process boot. No seeding."""
import itertools
import uuid
from datetime import datetime, timezone

_seq = itertools.count(1)

# One dict per entity type, keyed by id.
clients = {}
assessments = {}
meal_plans = {}
routes = {}
drivers = {}
deliveries = {}
wellness_checks = {}
welfare_alerts = {}
contributions = {}
vacation_holds = {}


def new_id():
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def next_seq():
    return next(_seq)


def base_record():
    """Common fields for a mutable resource: id, created_at, updated_at, version."""
    ts = iso(now())
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(record):
    """Record a mutation: bump version and refresh updated_at."""
    record["version"] += 1
    record["updated_at"] = iso(now())
