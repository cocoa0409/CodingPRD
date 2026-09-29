"""In-memory data store. The store starts empty on every boot: nothing is seeded."""

import threading

import constants
import util

LOCK = threading.RLock()

TABLE_NAMES = [
    "providers",
    "patients",
    "rooms",
    "procedure_types",
    "cases",
    "antibiotic_orders",
    "scopes",
    "reprocessing_logs",
    "specimens",
    "recalls",
    "referrals",
    "lots",
]


class Store(object):
    def __init__(self):
        self.tables = {}
        for name in TABLE_NAMES:
            self.tables[name] = {}
        # The logical UTC clock. Before any request moves it, it reads 2026-08-01T00:00:00Z.
        self.clock = util.parse_instant(constants.DEFAULT_CLOCK)
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def table(self, name):
        return self.tables[name]

    def get(self, name, row_id):
        if not isinstance(row_id, str):
            return None
        return self.tables[name].get(row_id)

    def insert(self, name, row):
        self.tables[name][row["id"]] = row
        return row

    def all_rows(self, name):
        """Every row of a table in ascending created_at order (insertion order breaks ties)."""
        return sorted(self.tables[name].values(), key=lambda r: (r["created_at"], r["_seq"]))

    def now(self):
        return self.clock

    def today(self):
        return self.clock.date()


store = Store()


def new_row(table_name, fields):
    """Create a row carrying the four common properties plus the supplied fields."""
    now = store.now()
    row = {
        "id": util.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    row.update(fields)
    return store.insert(table_name, row)


def touch(row):
    """Any row whose stored fields change has its version incremented once and updated_at refreshed."""
    row["version"] += 1
    row["updated_at"] = store.now()
    return row


def touch_once(row):
    """§2.4: a row whose fields change has its version incremented *once* for that request.

    Several cascade hops can land on the same patient inside one request; the counter
    still moves by exactly one.
    """
    try:
        from flask import g, has_request_context

        if not has_request_context():
            return touch(row)
        seen = getattr(g, "_touched_once", None)
        if seen is None:
            seen = set()
            g._touched_once = seen
        if id(row) in seen:
            return row
        seen.add(id(row))
    except RuntimeError:
        pass
    return touch(row)


def rows_where(table_name, predicate):
    return [r for r in store.all_rows(table_name) if predicate(r)]
