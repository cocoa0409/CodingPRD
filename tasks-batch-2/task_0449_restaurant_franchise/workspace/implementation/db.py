"""In-memory data store.

Storage is pure in-process Python dicts keyed by id. The store is constructed
empty at module load, so a fresh process (every per-test-server reboot) starts
with no state. There is NO file/SQLite/JSON persistence and NO seeding.

Common fields (PRD §2.4): every resource carries a UUID `id`, a `created_at`
(ISO 8601 UTC, 3 fractional digits), an `updated_at` (refreshed on each
mutation), and an integer `version` starting at 1 and incremented on each
mutation. All entities participate in the full common-field set.
"""
import threading
import uuid

from response import now_iso

# A coarse lock so each request's state mutations are atomic relative to others.
LOCK = threading.RLock()

# One dict per entity collection, keyed by id.
brands = {}
territories = {}
franchisees = {}
agreements = {}
units = {}
sales_reports = {}
royalty_statements = {}
vendors = {}
vendor_authorizations = {}
audits = {}
development_schedules = {}
national_accounts = {}

# Monotonic creation counter — guarantees a stable tie-break ordering distinct
# from created_at (which has only millisecond resolution and could collide).
_seq = 0


def new_id():
    return str(uuid.uuid4())


def next_seq():
    global _seq
    _seq += 1
    return _seq


def init_common(record):
    """Stamp id + common fields onto a freshly created record (PRD §2.4)."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Refresh updated_at and bump version on a mutation (PRD §2.4)."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record
