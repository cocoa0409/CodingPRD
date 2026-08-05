"""In-memory data store.

Everything lives in plain Python dictionaries keyed by id. There is no database,
no file, no cache and no other persistence of any kind: a fresh process starts
with a completely empty program, and no entity is ever seeded at import time.
"""

import threading
import uuid

import clock

# --- tables ---------------------------------------------------------------
TABLES = (
    "patients",
    "referrals",
    "assessments",
    "episodes",
    "visits",
    "compliance_days",
    "kits",
    "components",
    "lapses",
    "delivery_orders",
    "meal_plans",
    "escalations",
    "units",
    "reservations",
    "claims",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in TABLES:
            setattr(self, name, {})
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


DB = Store()


def new_id():
    return str(uuid.uuid4())


def make_row(table, fields, audited=True):
    """Create a row with the common fields of PRD 2.4 and insert it."""
    row = dict(fields)
    row["id"] = new_id()
    row["_seq"] = DB.next_seq()
    row["_table"] = table
    stamp = clock.audit_stamp()
    row["created_at"] = stamp
    row["_created_dt"] = clock.now_dt()
    if audited:
        row["updated_at"] = stamp
        row["version"] = 1
    getattr(DB, table)[row["id"]] = row
    _request_created().add(row["id"])
    return row


# --- per-request mutation tracking ---------------------------------------
# PRD 2.4/2.9: every row a request mutates -- including secondary rows reached
# by a cascade -- gets exactly one version bump and a refreshed updated_at.

_LOCAL = threading.local()


def _state():
    if not hasattr(_LOCAL, "dirty"):
        _LOCAL.dirty = []
        _LOCAL.created = set()
        _LOCAL.snapshots = {}
    return _LOCAL


def begin_request():
    _LOCAL.dirty = []
    _LOCAL.created = set()
    _LOCAL.snapshots = {}


def _request_created():
    return _state().created


def touch(row):
    """Mark a row as mutated by the current request."""
    if row is None:
        return
    state = _state()
    if row["id"] in state.created:
        return
    for existing in state.dirty:
        if existing is row:
            return
    state.dirty.append(row)


def snapshot_derived():
    """Record the derived-field fingerprint of every episode and inpatient unit.

    PRD 2.4 counts an indirectly recomputed roll-up ("an episode's day-ledger
    counters being recomputed after a compliance day flips", "a bed census
    shifting because a sibling reservation expired") as a mutation of that row.
    """
    import derived

    snaps = {}
    for episode in DB.episodes.values():
        snaps[("episodes", episode["id"])] = derived.episode_fingerprint(episode)
    for unit in DB.units.values():
        snaps[("units", unit["id"])] = derived.unit_fingerprint(unit)
    _state().snapshots = snaps


def flush():
    """Apply the version bumps of the current request, then clear the tracker."""
    import derived

    state = _state()
    snaps = state.snapshots or {}
    for episode in DB.episodes.values():
        key = ("episodes", episode["id"])
        if key in snaps and snaps[key] != derived.episode_fingerprint(episode):
            touch(episode)
    for unit in DB.units.values():
        key = ("units", unit["id"])
        if key in snaps and snaps[key] != derived.unit_fingerprint(unit):
            touch(unit)

    stamp = clock.audit_stamp()
    for row in state.dirty:
        if "version" in row:
            row["version"] = row["version"] + 1
            row["updated_at"] = stamp
    state.dirty = []
    state.created = set()
    state.snapshots = {}


# --- ordering -------------------------------------------------------------

def sort_key(row):
    """PRD 2.3: list endpoints sort by created_at ascending, insertion order breaks ties."""
    return (row["_created_dt"], row["_seq"])


def ordered(rows):
    return sorted(rows, key=sort_key)


def all_rows(table):
    return ordered(getattr(DB, table).values())
