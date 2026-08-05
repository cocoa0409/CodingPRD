"""In-memory data store, logical clock and the per-request transaction.

Storage is Python dicts only.  Nothing is persisted, nothing is seeded: the
store is empty on every boot and every entity is created by an API caller.

The transaction implements two PRD 2.4 rules centrally rather than per
handler:

  * "A request that is rejected by any rung of the validation ladder writes
    nothing at all" -- the whole store is snapshotted at request entry and
    restored verbatim on any rejection.
  * "Within the handling of a single request a given resource's `version`
    advances at most once, no matter how many cascade hops touch it" -- at
    commit time each pre-existing row is diffed against its snapshot and gets
    exactly one `version` bump plus one `updated_at` refresh when any stored
    attribute changed.
"""

import copy
import threading
import uuid

from . import constants, timeutil

KINDS = [
    "employer",
    "site",
    "contract",
    "provider",
    "shift",
    "eligibility",
    "participant",
    "appointment",
    "visit",
    "assessment",
    "referral",
    "alt_standard",
    "award",
    "period",
]

tables = {kind: {} for kind in KINDS}

_seq = 0

# --- logical clock ----------------------------------------------------------
# The initial reading goes through fmt_instant like every other instant, so
# the very first `created_at` this server writes already carries the canonical
# three fractional digits rather than the constant's shorter spelling.
_clock_dt = timeutil.parse_instant(constants.DEFAULT_CLOCK_UTC)
_clock_iso = timeutil.fmt_instant(_clock_dt)

request_lock = threading.RLock()


class Txn(object):
    """Per-request bookkeeping."""

    def __init__(self):
        self.snapshot_tables = copy.deepcopy(tables)
        self.snapshot_seq = _seq
        self.snapshot_clock = _clock_iso
        self.forced = set()
        self.created = set()
        # Response payloads projected from live rows during this request.  They
        # are captured by the handler BEFORE commit() applies the at-most-once
        # version bump, so commit() refreshes them in place -- PRD 2.4: "Every
        # stored attribute of a resource is response-visible ... by any
        # operation that mutates the resource."
        self.dumps = []


_txn = threading.local()


def current_txn():
    return getattr(_txn, "value", None)


def begin():
    _txn.value = Txn()
    return _txn.value


def rollback():
    global tables, _seq
    txn = current_txn()
    if txn is None:
        return
    tables = txn.snapshot_tables
    _seq = txn.snapshot_seq
    set_clock(txn.snapshot_clock)
    _txn.value = None


def clear_txn():
    _txn.value = None


def commit():
    """Apply the at-most-once version bump to every changed pre-existing row."""
    txn = current_txn()
    if txn is None:
        return
    stamp = now_iso()
    for kind, rows in tables.items():
        snap_rows = txn.snapshot_tables.get(kind, {})
        for rid, row in rows.items():
            old = snap_rows.get(rid)
            if old is None:
                continue  # created during this request; stays at version 1
            forced = (kind, rid) in txn.forced
            if forced or _differs(row, old):
                row["version"] = old["version"] + 1
                row["updated_at"] = stamp
    # Re-sync every projection handed to the response with the row it came
    # from, so a mutating response reports the post-write version/updated_at.
    for projection, row in txn.dumps:
        if "version" in projection:
            projection["version"] = row["version"]
        if "updated_at" in projection:
            projection["updated_at"] = row["updated_at"]
    _txn.value = None


def register_projection(projection, row):
    """Record a response payload built from a live row (see Txn.dumps)."""
    txn = current_txn()
    if txn is not None:
        txn.dumps.append((projection, row))


def _differs(row, old):
    keys = set(row) | set(old)
    for key in keys:
        if key in ("version", "updated_at"):
            continue
        if row.get(key, None) != old.get(key, None):
            return True
    return False


def force_version_bump(kind, row):
    """Advance a row's version even when no stored attribute changed.

    Used only where the PRD declares a version bump as an unconditional side
    effect: the site calendar update and the appointment reschedule (PRD 3.4:
    "the site's `version` rises by one because day-level occupancy changed,
    but the site's slot counters do not move").
    """
    txn = current_txn()
    if txn is not None:
        txn.forced.add((kind, row["id"]))


# --- clock ------------------------------------------------------------------

def now_iso():
    return _clock_iso


def now_dt():
    return _clock_dt


def now_date():
    return _clock_dt.date()


def set_clock(iso_value):
    global _clock_iso, _clock_dt
    dt = timeutil.parse_instant(iso_value)
    _clock_dt = dt
    _clock_iso = timeutil.fmt_instant(dt)
    return _clock_iso


def reset_clock():
    set_clock(constants.DEFAULT_CLOCK_UTC)


# --- rows -------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def insert(kind, fields):
    """Create a row with the four common properties (PRD 2.4)."""
    global _seq
    _seq += 1
    stamp = now_iso()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    row.update(fields)
    row["_seq"] = _seq
    tables[kind][row["id"]] = row
    txn = current_txn()
    if txn is not None:
        txn.created.add((kind, row["id"]))
    return row


def get(kind, rid):
    if not isinstance(rid, str):
        return None
    return tables[kind].get(rid)


def all_rows(kind):
    return list(tables[kind].values())


def sorted_rows(kind, rows=None):
    """PRD 2.3: list results are ordered by `created_at` ascending.

    Insertion sequence breaks ties, because the logical clock does not move
    between two creations made at the same instant.
    """
    if rows is None:
        rows = all_rows(kind)
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def reset_all():
    global tables, _seq
    tables = {kind: {} for kind in KINDS}
    _seq = 0
    reset_clock()
