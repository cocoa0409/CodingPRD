"""Per-request transaction bookkeeping.

A snapshot of every row is taken at the start of a request.  On success the
snapshot decides which rows actually changed, and each changed row gets exactly
one `updated_at` refresh and one `version` increment for the request -- including
rows mutated by a cascade rather than by the direct request (PRD 2.4, 2.7).  On
failure the snapshot is restored so no partially applied mutation survives a
rejected request.
"""

from flask import g

import db
import derive
from db import store


def begin():
    snapshot = {}
    for kind, table in store.tables.items():
        for row_id, row in table.items():
            snapshot[(kind, row_id)] = dict(row)
    g.tx_snapshot = snapshot
    g.tx_forced_agencies = set()
    g.tx_committed = False


def force_agency_version_bump(agency):
    """PRD records an explicit `Agency.version incremented by 1` on a number of
    transitions even when no other agency field moves."""
    g.tx_forced_agencies.add(agency["id"])


def _changed(row, old):
    keys = set(row.keys()) | set(old.keys())
    for key in keys:
        if key in ("version", "updated_at") or key.startswith("_"):
            continue
        if row.get(key, None) != old.get(key, None):
            return True
    return False


def commit():
    if getattr(g, "tx_committed", False):
        return
    g.tx_committed = True
    snapshot = getattr(g, "tx_snapshot", None)
    if snapshot is None:
        return

    # Derived agency values are never stale (PRD 2.6).
    for agency in store.all(db.AGENCY):
        derive.recompute_agency(agency)

    forced = getattr(g, "tx_forced_agencies", set())
    stamp = db.now_iso()
    for (kind, row_id), old in snapshot.items():
        row = store.tables[kind].get(row_id)
        if row is None:
            continue
        if _changed(row, old) or (kind == db.AGENCY and row_id in forced):
            row["version"] = old.get("version", 1) + 1
            row["updated_at"] = stamp


def rollback():
    snapshot = getattr(g, "tx_snapshot", None)
    if snapshot is None:
        return
    for kind, table in store.tables.items():
        for row_id in list(table.keys()):
            if (kind, row_id) not in snapshot:
                del table[row_id]
    for (kind, row_id), old in snapshot.items():
        store.tables[kind][row_id] = old
