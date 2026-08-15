"""In-memory data store. Starts empty on every boot; nothing is ever seeded."""
import itertools

import util

STORE = {
    "flocks": {},
    "seasons": {},
    "births": {},
    "pastures": {},
    "moves": {},
    "treatments": {},
    "crews": {},
    "shearings": {},
    "clips": {},
    "lots": {},
    "core_tests": {},
    "consignments": {},
    "holidays": {},
    "sales": {},
    "losses": {},
    "contracts": {},
}

_seq = itertools.count(1)


def new_row():
    """Fresh common fields for a mutable resource."""
    now = util.now_utc()
    return {
        "id": util.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "seq": next(_seq),
    }


def new_birth_row():
    """BirthRecord carries only id + created_at (no updated_at / version)."""
    return {
        "id": util.new_id(),
        "created_at": util.now_utc(),
        "seq": next(_seq),
    }


def touch(row):
    """Register a mutation: refresh updated_at and increment version by exactly 1."""
    row["updated_at"] = util.now_utc()
    row["version"] += 1


def get_or_404(kind, rid):
    row = STORE[kind].get(rid)
    if row is None:
        from errors import ERR_NOT_FOUND, raise_err
        raise_err(ERR_NOT_FOUND, "resource not found: %s" % rid)
    return row


def sorted_rows(kind):
    """Deterministic list order: created_at ascending, insertion order as tiebreak."""
    return sorted(STORE[kind].values(), key=lambda r: (r["created_at"], r["seq"]))
