"""In-memory store.  Plain Python dicts, nothing else.

No SQLite, no file, no pickle, no /tmp cache.  Every collection starts EMPTY on
every boot; no row is ever seeded, preloaded or hardcoded here or anywhere else.
Per-test-server isolation relaunches the process before every test and relies on
exactly that.
"""

from . import clock, ids

COLLECTIONS = (
    "clinics",
    "contracts",
    "mobile_units",
    "equipment",
    "technicians",
    "specialists",
    "routes",
    "route_stops",
    "referrals",
    "appointments",
    "studies",
    "read_assignments",
    "reports",
    "qc_checks",
    "peer_reviews",
    "invoices",
    "charge_lines",
    "block_ledger_entries",
    "notifications",
    "holds",  # internal: closed pause windows per study, not an API resource
)

store = {name: {} for name in COLLECTIONS}


def reset():
    for name in COLLECTIONS:
        store[name] = {}
    ids.reset()
    clock.reset()


def table(name):
    return store[name]


def insert(name, record):
    store[name][record["id"]] = record
    return record


def get(name, key):
    if not isinstance(key, str):
        return None
    return store[name].get(key)


def all_rows(name):
    """Every row in creation order (dict insertion order == monotonic id order)."""
    return list(store[name].values())


def where(name, **filters):
    out = []
    for row in store[name].values():
        ok = True
        for k, v in filters.items():
            if row.get(k) != v:
                ok = False
                break
        if ok:
            out.append(row)
    return out


def new_record(with_version=True):
    """A fresh record skeleton.

    `_seq` is the monotonic creation ordinal; list sorting uses (created_at, _seq)
    so ties at the coarse logical clock resolve deterministically.
    """
    seq = ids.next_seq()
    now = clock.now()
    rec = {"id": ids.new_id(seq), "_seq": seq, "created_at": now}
    if with_version:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    """One declared mutation step against `rec`: refresh updated_at, bump version."""
    if rec is None:
        return rec
    if "version" in rec:
        rec["version"] = rec["version"] + 1
        rec["updated_at"] = clock.now()
    return rec


def sort_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
