"""Shared helpers for the route modules."""

import db
import validate
from errors import ApiError
from response import list_response, object_response

PREFIX = "/cancer-registry"


def need(kind, oid, error_id):
    obj = db.get(kind, oid)
    if obj is None:
        raise ApiError(error_id)
    return obj


def ok(obj, status=200):
    db.commit()
    return object_response(db.public(obj), status)


def ok_data(data, status=200):
    db.commit()
    return object_response(data, status)


def page(items):
    limit, offset = validate.pagination()
    total = len(items)
    window = items[offset:offset + limit]
    return list_response([db.public(o) for o in window], limit, offset, total)


def matches(obj, field, value):
    return value is None or obj.get(field) == value
