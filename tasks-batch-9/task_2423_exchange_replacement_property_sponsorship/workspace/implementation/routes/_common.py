"""Shared read helpers for the route modules."""
import db
import middleware
from response import array_response, object_response
from services import domain


def listing(collection, roles, str_filters=(), int_filters=()):
    middleware.actor(roles)
    limit, offset = middleware.pagination()
    conditions = {}
    for name in str_filters:
        value = middleware.filter_arg(name)
        if value is not None:
            conditions[name] = value
    for name in int_filters:
        value = middleware.int_filter_arg(name)
        if value is not None:
            conditions[name] = value
    rows = [
        row for row in db.sorted_rows(collection)
        if all(row.get(key) == value for key, value in conditions.items())
    ]
    total = len(rows)
    window = rows[offset:offset + limit]
    return array_response([db.serialize(row) for row in window], limit, offset, total)


def read_one(kind, roles, row_id):
    middleware.actor(roles)
    row = domain.require(kind, row_id)
    return object_response(db.serialize(row))
