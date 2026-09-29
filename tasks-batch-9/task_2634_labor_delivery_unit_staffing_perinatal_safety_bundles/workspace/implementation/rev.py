"""Per-request revision bookkeeping.

PRD 2.4: `version` increments by 1 on each mutation of a record. A single
request cascades across many records, and each such record's counter moves by
exactly one, so a record touched several times inside one request still only
advances once.
"""

from flask import g

import clock


def _seen():
    bag = getattr(g, "_touched_ids", None)
    if bag is None:
        bag = set()
        g._touched_ids = bag
    return bag


def touch(rec):
    if rec is None:
        return None
    bag = _seen()
    if rec["id"] in bag:
        rec["updated_at"] = clock.now()
        return rec
    bag.add(rec["id"])
    rec["updated_at"] = clock.now()
    rec["version"] = rec.get("version", 1) + 1
    return rec


def touched(rec):
    return rec is not None and rec["id"] in _seen()
