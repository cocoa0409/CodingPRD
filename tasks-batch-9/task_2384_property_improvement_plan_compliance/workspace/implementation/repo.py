"""Row lookup, ordering, serialisation and list-page helpers."""

from db import db, fmt_ts, clock_now, new_id
from errors import ApiError
from response import list_response, object_response

# collection attribute -> not-found error id
NOT_FOUND = {
    "franchisees": "ERR_FRANCHISEE_NOT_FOUND",
    "properties": "ERR_PROPERTY_NOT_FOUND",
    "plans": "ERR_PLAN_NOT_FOUND",
    "items": "ERR_ITEM_NOT_FOUND",
    "extension_requests": "ERR_EXTENSION_REQUEST_NOT_FOUND",
    "budgets": "ERR_BUDGET_NOT_FOUND",
    "draws": "ERR_DRAW_NOT_FOUND",
    "phases": "ERR_PHASE_NOT_FOUND",
    "contractors": "ERR_CONTRACTOR_NOT_FOUND",
    "bookings": "ERR_BOOKING_NOT_FOUND",
    "inspections": "ERR_INSPECTION_NOT_FOUND",
    "punch_items": "ERR_PUNCH_NOT_FOUND",
    "disputes": "ERR_DISPUTE_NOT_FOUND",
    "notices": "ERR_NOTICE_NOT_FOUND",
    "ledger": "ERR_LEDGER_ENTRY_NOT_FOUND",
}


def collection(name):
    return getattr(db, name)


def find(name, row_id):
    if not isinstance(row_id, str):
        return None
    return collection(name).get(row_id)


def must_find(name, row_id):
    row = find(name, row_id)
    if row is None:
        raise ApiError(NOT_FOUND[name])
    return row


def rows(name):
    """All rows of a collection in canonical order (created_at asc, stable)."""
    return sorted(collection(name).values(), key=lambda r: (r["created_at"], r["_seq"]))


def insert(name, row):
    collection(name)[row["id"]] = row
    return row


def new_row(extra_fields, versioned=True):
    """Builds the system-field skeleton for a new row."""
    now = fmt_ts(clock_now())
    row = {"id": new_id()}
    row.update(extra_fields)
    row["created_at"] = now
    if versioned:
        row["updated_at"] = now
        row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """A row has been advanced: refresh updated_at and increment version."""
    row["updated_at"] = fmt_ts(clock_now())
    row["version"] = row["version"] + 1


def serialize(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def serialize_many(rowset):
    return [serialize(r) for r in rowset]


def single(row, http_status=200):
    return object_response(serialize(row), http_status)


def page(rowset, limit, offset):
    total = len(rowset)
    window = rowset[offset:offset + limit]
    return list_response(serialize_many(window), limit, offset, total)
