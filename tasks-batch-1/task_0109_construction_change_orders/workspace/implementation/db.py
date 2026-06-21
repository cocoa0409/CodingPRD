"""In-memory data store (PRD §2.4).

All state is held in module-level dicts keyed by id. The store starts EMPTY on
every process boot — nothing is seeded. The test harness restarts the server
before every test, so this module's import-time state must contain no entities.

Common-field entities carry: id, created_at, updated_at, version.
PayAppLine is the single exception: only id + created_at (PRD §2.4).
"""
import itertools
import threading
import uuid

from response import now_iso

# One dict per entity collection, keyed by id.
projects = {}
sov_lines = {}
change_orders = {}
pay_applications = {}
pay_app_lines = {}
subcontractor_commitments = {}
rfis = {}
submittals = {}
lien_waivers = {}
punch_items = {}
inspection_windows = {}
retention_releases = {}

_lock = threading.RLock()

# Monotonic creation sequence so we have a stable tie-break / insertion order
# even when two records share the same millisecond created_at timestamp.
_seq_counter = itertools.count(1)


def new_id():
    # Server-minted UUID with no type prefix (PRD §2.4).
    return str(uuid.uuid4())


def next_seq():
    return next(_seq_counter)


def stamp_create(record):
    """Attach common system fields on first creation (versioned entities)."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def stamp_create_line(record):
    """PayAppLine: only id + created_at, no updated_at/version (PRD §2.4)."""
    record["id"] = new_id()
    record["created_at"] = now_iso()
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Bump updated_at + version on a mutation of a versioned record."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1


def public(record):
    """Strip internal-only keys (those prefixed with '_') for serialization."""
    return {k: v for k, v in record.items() if not k.startswith("_")}
