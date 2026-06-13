"""Existence lookups (PRD §2.7 / validation priority 3 -> ERR_NOT_FOUND).

Path/body referenced resources are validated left-to-right; a missing
reference raises ERR_NOT_FOUND (404).
"""
import db
from errors import err, ERR_NOT_FOUND


def _get(coll, rid):
    if rid is None:
        err(ERR_NOT_FOUND, "missing resource id")
    rec = coll.get(rid)
    if rec is None:
        err(ERR_NOT_FOUND, "resource not found")
    return rec


def league(rid):
    return _get(db.leagues, rid)


def official(rid):
    return _get(db.officials, rid)


def game(rid):
    return _get(db.games, rid)


def crew_slot(rid):
    return _get(db.crew_slots, rid)


def assignment(rid):
    return _get(db.assignments, rid)


def availability(rid):
    return _get(db.availabilities, rid)


def conflict(rid):
    return _get(db.conflict_declarations, rid)


def appeal(rid):
    return _get(db.penalty_appeals, rid)
