"""In-memory store. Nothing is persisted to disk and nothing is ever seeded."""
import itertools
import uuid

from flask import g

import clock

TABLES = (
    "terminals",
    "customers",
    "tariff_versions",
    "commodity_profiles",
    "rate_programs",
    "exception_agreements",
    "shipments",
    "shipment_lines",
    "capture_events",
    "inspection_findings",
    "correction_notices",
    "disputes",
    "credit_memos",
    "repricing_runs",
)


class Store:
    def __init__(self):
        self.tables = {name: {} for name in TABLES}
        self.counter = itertools.count(1)

    def table(self, name):
        return self.tables[name]


store = Store()


def table(name):
    return store.tables[name]


# convenient module-level accessors ------------------------------------------
def terminals():
    return store.tables["terminals"]


def customers():
    return store.tables["customers"]


def tariff_versions():
    return store.tables["tariff_versions"]


def commodity_profiles():
    return store.tables["commodity_profiles"]


def rate_programs():
    return store.tables["rate_programs"]


def exception_agreements():
    return store.tables["exception_agreements"]


def shipments():
    return store.tables["shipments"]


def shipment_lines():
    return store.tables["shipment_lines"]


def capture_events():
    return store.tables["capture_events"]


def inspection_findings():
    return store.tables["inspection_findings"]


def correction_notices():
    return store.tables["correction_notices"]


def disputes():
    return store.tables["disputes"]


def credit_memos():
    return store.tables["credit_memos"]


def repricing_runs():
    return store.tables["repricing_runs"]


def insert(name, data, versioned=True):
    row = dict(data)
    row["id"] = str(uuid.uuid4())
    row["created_at"] = clock.now()
    row["_seq"] = next(store.counter)
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    store.tables[name][row["id"]] = row
    return row


def touch(row):
    """Refresh updated_at / bump version, at most once per row per request."""
    if row is None or "version" not in row:
        return row
    try:
        seen = g._touched
    except (AttributeError, RuntimeError):
        seen = None
    if seen is None:
        seen = set()
        try:
            g._touched = seen
        except RuntimeError:
            pass
    if row["id"] in seen:
        row["updated_at"] = clock.now()
        return row
    seen.add(row["id"])
    row["updated_at"] = clock.now()
    row["version"] = int(row["version"]) + 1
    return row


def _sort_key(row):
    return (row["created_at"], row["_seq"])


def all_rows(name, predicate=None):
    rows = [r for r in store.tables[name].values() if predicate is None or predicate(r)]
    rows.sort(key=_sort_key)
    return rows


def get(name, row_id):
    if not isinstance(row_id, str):
        return None
    return store.tables[name].get(row_id)
