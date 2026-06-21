"""In-memory data store.

Every collection is a dict keyed by the resource id (UUID, no type prefix).
The store starts EMPTY on every process boot — nothing is seeded. All entities
are created by the test harness through the declared API surface.

Common system fields (PRD §2.4):
  - id          : UUID string, no type prefix
  - created_at  : ISO8601 UTC, three fractional digits, set once
  - updated_at  : ISO8601 UTC, refreshed on every mutation
  - version     : integer starting at 1, +1 on each mutation
"""

import itertools
import uuid

from response import now_iso

# ---------------------------------------------------------------------------
# Collections — one dict per entity, keyed by id.
# ---------------------------------------------------------------------------
parts = {}
vendors = {}
avl_entries = {}
inventory_lots = {}
boms = {}
bom_lines = {}
work_orders = {}
kit_requirements = {}
line_programs = {}
units = {}
rework_orders = {}
ecos = {}
rmas = {}

# Monotonic counters used purely to derive stable created ordering / serials.
# created_at strings can collide (millisecond resolution); a monotonic seq
# guarantees deterministic FIFO tie-breaks and list ordering.
_seq_counter = itertools.count(1)
_serial_counter = itertools.count(1)


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


def mint_serial():
    return "SN-" + f"{next(_serial_counter):08d}"


def new_record(extra_fields):
    """Create a record dict with system fields populated.

    `extra_fields` is merged in; any system field present there is overridden
    by the canonical system value.
    """
    rid = new_id()
    ts = now_iso()
    rec = dict(extra_fields)
    rec["id"] = rid
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    # internal ordering key, not surfaced in responses
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """Bump version and updated_at for a mutated record."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = now_iso()
    return rec
