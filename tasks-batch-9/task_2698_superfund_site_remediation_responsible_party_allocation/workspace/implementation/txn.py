"""Per-request version/updated_at bookkeeping.

PRD 2.4: `version` starts at 1 and increases by exactly 1 on every mutation,
*including* mutations that only touch derived fields — and by exactly 1, not
once per field.  So every mutating helper registers the record it is about to
change, and at the end of the request each registered record is compared with
its snapshot; the ones that actually changed get a single bump.
"""

from flask import g

import logical_clock

SKIP = ("version", "updated_at")


def _snapshot(record):
    out = {}
    for key, value in record.items():
        if key in SKIP:
            continue
        out[key] = list(value) if isinstance(value, list) else value
    return out


def _registry():
    reg = getattr(g, "_txn_registry", None)
    if reg is None:
        reg = {}
        g._txn_registry = reg
    return reg


def watch(record):
    """Register a versioned record before mutating it.  Immutable record types
    (which carry only id and created_at) have no version and are ignored."""
    if record is None or "version" not in record:
        return record
    reg = _registry()
    key = id(record)
    if key not in reg:
        reg[key] = (record, _snapshot(record))
    return record


def force(record):
    """PRD 3.6/3.9: opening an allocation round increments the *site's* version
    and opening a recovery action increments the *respondent's* version, even
    though neither write changes a field on those records.  Register them for an
    unconditional single bump."""
    if record is None or "version" not in record:
        return record
    watch(record)
    forced = getattr(g, "_txn_forced", None)
    if forced is None:
        forced = set()
        g._txn_forced = forced
    forced.add(id(record))
    return record


def commit():
    stamp = logical_clock.now()
    forced = getattr(g, "_txn_forced", None) or set()
    for key, (record, snap) in _registry().items():
        if key in forced or _snapshot(record) != snap:
            record["version"] += 1
            record["updated_at"] = stamp
