"""Process-local in-memory store.

Every byte of state lives in this module's `db` singleton, so a fresh process
(one `start.sh` invocation) always starts completely empty.  Nothing is ever
seeded here: tests build all entity state through the declared endpoints.
"""
import uuid

from util import DEFAULT_CLOCK_ISO, parse_dt

COLLECTIONS = (
    "contracts",
    "cost_tiers",
    "sites",
    "stocks",
    "devices",
    "technicians",
    "meter_reads",
    "periods",
    "statements",
    "lines",
    "orders",
    "tickets",
    "reviews",
    "removals",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0
        self.clock = parse_dt(DEFAULT_CLOCK_ISO)

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock

    def sorted_rows(self, collection):
        """Rows in default list order: created_at ASC, insertion order as tiebreak."""
        rows = list(getattr(self, collection).values())
        rows.sort(key=lambda r: (r.get("created_at") or self.clock, r["_seq"]))
        return rows


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_row(with_common=True):
    """Allocate a bare record with id / created_at / updated_at / version."""
    row = {"id": new_id(), "_seq": db.next_seq(), "created_at": db.clock}
    if with_common:
        row["updated_at"] = db.clock
        row["version"] = 1
    return row


def _touched_set():
    try:
        from flask import g, has_request_context

        if not has_request_context():
            return None
        if not hasattr(g, "_touched_rows"):
            g._touched_rows = set()
        return g._touched_rows
    except Exception:
        return None


def touch(row):
    """Bump version/updated_at at most once per request for a given row.

    PRD 2.4 says `version` increases by exactly 1 on every mutation of the row,
    and PRD 2.6 pins that to *once per operation* even when several hops of one
    cascade touch the same row (e.g. both device state dimensions moving).
    """
    if row is None or "version" not in row:
        return row
    seen = _touched_set()
    key = id(row)
    if seen is not None:
        if key in seen:
            row["updated_at"] = db.clock
            return row
        seen.add(key)
    row["version"] += 1
    row["updated_at"] = db.clock
    return row
