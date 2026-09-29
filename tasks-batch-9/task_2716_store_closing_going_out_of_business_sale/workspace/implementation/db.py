"""In-memory store. Starts empty on every boot; nothing is ever seeded."""

import itertools
import uuid

import clock

TABLES = (
    "jurisdictions",
    "engagements",
    "stores",
    "lots",
    "consignments",
    "stages",
    "licenses",
    "employees",
    "sales_days",
    "expense_items",
    "leases",
    "settlements",
)

_data = {name: {} for name in TABLES}
_seq = itertools.count(1)


def table(name):
    return _data[name]


def reset():
    global _seq
    for name in TABLES:
        _data[name].clear()
    _seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def insert(table_name, row):
    """Attach the common system fields and store the row."""
    row["id"] = new_id()
    stamp = clock.iso_now()
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    row["_seq"] = next(_seq)
    row["_created"] = clock.now()
    _data[table_name][row["id"]] = row
    return row


def touch(row):
    """Bump version and refresh updated_at (PRD 2.4 / 2.9)."""
    if row is None:
        return None
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = clock.iso_now()
    return row


def refresh(row):
    """Refresh updated_at without bumping version (pure roll-up recompute)."""
    if row is None:
        return None
    row["updated_at"] = clock.iso_now()
    return row


def get(table_name, row_id):
    if not isinstance(row_id, str):
        return None
    return _data[table_name].get(row_id)


def order_key(row):
    return (row["_created"], row["_seq"])


def all_rows(table_name):
    return sorted(_data[table_name].values(), key=order_key)


def where(table_name, **filters):
    out = []
    for row in _data[table_name].values():
        keep = True
        for key, value in filters.items():
            if row.get(key) != value:
                keep = False
                break
        if keep:
            out.append(row)
    out.sort(key=order_key)
    return out


# ---------------------------------------------------------------- navigation

def stores_of_engagement(engagement_id):
    return where("stores", engagement_id=engagement_id)


def lots_of_store(store_id):
    return where("lots", store_id=store_id)


def lots_of_engagement(engagement_id):
    out = []
    for store in stores_of_engagement(engagement_id):
        out.extend(lots_of_store(store["id"]))
    out.sort(key=order_key)
    return out


def stages_of_store(store_id):
    return where("stages", store_id=store_id)


def licenses_of_store(store_id):
    return where("licenses", store_id=store_id)


def consignments_of_store(store_id):
    return where("consignments", store_id=store_id)


def employees_of_store(store_id):
    return where("employees", store_id=store_id)


def sales_days_of_store(store_id):
    return where("sales_days", store_id=store_id)


def leases_of_store(store_id):
    return where("leases", store_id=store_id)


def expense_items_of_engagement(engagement_id):
    return where("expense_items", engagement_id=engagement_id)


def expense_items_of_store(store_id):
    return where("expense_items", store_id=store_id)


def settlements_of_engagement(engagement_id):
    return where("settlements", engagement_id=engagement_id)


def sales_days_of_engagement(engagement_id):
    out = []
    for store in stores_of_engagement(engagement_id):
        out.extend(sales_days_of_store(store["id"]))
    out.sort(key=order_key)
    return out


def employees_of_engagement(engagement_id):
    out = []
    for store in stores_of_engagement(engagement_id):
        out.extend(employees_of_store(store["id"]))
    out.sort(key=order_key)
    return out
