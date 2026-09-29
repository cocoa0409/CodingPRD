"""Helpers shared by the route modules."""

import db
import response
import validate


def list_response(rows, projector):
    limit, offset = validate.pagination()
    page, total = validate.paginate(rows, limit, offset)
    return response.listing([projector(row) for row in page], limit, offset, total)


def collection(name):
    return db.ordered(getattr(db.store, name))


def match(row, field, value):
    if value is None:
        return True
    return row.get(field) == value
