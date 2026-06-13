"""In-memory data store. All state lives in module-level dicts keyed by id.

No seeding, no preloading: every dict starts empty on process boot. The test
harness restarts the server via start.sh before every test, so module import
must produce an empty store.
"""
import uuid

from response import now_iso

# One dict per entity type, keyed by id (UUID string, no prefix).
institutions = {}
terms = {}
students = {}
plan_templates = {}
enrollments = {}
installments = {}
charges = {}
aids = {}
payments = {}
late_fees = {}
holds = {}
withdrawals = {}


def new_id():
    return str(uuid.uuid4())


def stamp_new(record):
    """Populate system-managed common fields on a freshly created resource."""
    ts = now_iso()
    record.setdefault("id", new_id())
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    """Mark a resource mutated: refresh updated_at, bump version by one."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record
