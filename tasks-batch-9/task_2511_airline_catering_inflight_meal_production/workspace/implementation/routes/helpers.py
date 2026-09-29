"""Helpers shared by every route module."""

import db
import middleware
import response
import serialize
import validate
from errors import fail

# ---------------------------------------------------------------------------
# airline resolution used by ownership filtering (PRD 2.10)


def _airline_of_flight_id(flight_id):
    flight = db.get("flights", flight_id)
    return flight["airline_id"] if flight else None


def _airline_of_cart(row):
    return _airline_of_flight_id(row["flight_id"])


def _airline_of_item(row):
    cart = db.get("carts", row["cart_id"])
    return _airline_of_cart(cart) if cart else None


def _airline_of_run(row):
    manifest = db.get("loading_manifests", row["loading_manifest_id"])
    return _airline_of_flight_id(manifest["flight_id"]) if manifest else None


def _airline_of_waste(row):
    record = db.get("uplift_records", row["uplift_record_id"])
    return _airline_of_flight_id(record["flight_id"]) if record else None


def _airline_of_check(row):
    batch = db.get("production_batches", row["production_batch_id"])
    return _airline_of_flight_id(batch["flight_id"]) if batch else None


RESOLVERS = {
    "airlines": lambda row: row["id"],
    "meal_specifications": lambda row: row["airline_id"],
    "flights": lambda row: row["airline_id"],
    "special_meal_orders": lambda row: _airline_of_flight_id(row["flight_id"]),
    "production_batches": lambda row: _airline_of_flight_id(row["flight_id"]),
    "haccp_checks": _airline_of_check,
    "carts": _airline_of_cart,
    "cart_items": _airline_of_item,
    "loading_manifests": lambda row: _airline_of_flight_id(row["flight_id"]),
    "delivery_runs": _airline_of_run,
    "uplift_records": lambda row: _airline_of_flight_id(row["flight_id"]),
    "waste_manifests": _airline_of_waste,
    "audit_findings": lambda row: row["airline_id"],
}

# Collections whose detail read declares ERR_AIRLINE_SCOPE_VIOLATION; the same
# set is filtered on list reads.
SCOPED = (
    "airlines",
    "meal_specifications",
    "flights",
    "special_meal_orders",
    "production_batches",
    "carts",
    "loading_manifests",
    "delivery_runs",
    "uplift_records",
    "waste_manifests",
    "audit_findings",
)


def guard_scope(collection, row):
    if collection in SCOPED:
        middleware.require_scope(RESOLVERS[collection](row))


def visible(collection, rows):
    if collection not in SCOPED:
        return rows
    return middleware.scoped(rows, RESOLVERS[collection])


# ---------------------------------------------------------------------------


def resolve(collection, row_id, error_id="ERR_RESOURCE_NOT_FOUND"):
    row = db.get(collection, row_id)
    if row is None:
        fail(error_id)
    return row


def apply_filters(rows, filters):
    out = rows
    for key, value in filters.items():
        out = [row for row in out if row.get(key) == value]
    return out


def listing(collection, rows, filters, limit, offset, order=None):
    rows = apply_filters(rows, filters)
    rows = visible(collection, rows)
    if order is not None:
        rows = sorted(rows, key=order)
    items, total = validate.page(rows, limit, offset)
    return response.collection(serialize.many(collection, items), limit, offset, total)


def one(collection, row, status=200):
    return response.ok(serialize.one(collection, row), status)


def created(collection, row):
    return one(collection, row, 201)


def simple_list(collection, params, order=None):
    """The common list endpoint: validate query, filter, scope, page."""
    filters, limit, offset = validate.pagination(params)
    return listing(collection, db.rows(collection), filters, limit, offset, order=order)
