"""Small shared helpers for the route modules."""

from flask import request

import db
import response


def query_filters(records, fields):
    """Apply the collection's fixed set of equality filters."""
    args = request.args
    out = []
    for record in records:
        keep = True
        for field in fields:
            wanted = args.get(field)
            if wanted is None:
                continue
            actual = record.get(field)
            if actual is None:
                keep = False
                break
            if str(actual) != wanted:
                keep = False
                break
        if keep:
            out.append(record)
    return out


def listing(records, fields, extra=None):
    """Filter, narrow, order and page a collection."""
    rows = query_filters(list(records), fields)
    if extra is not None:
        rows = [r for r in rows if extra(r)]
    return response.collection_response(db.ordered(rows))


def one(record):
    return response.object_response(db.public(record))


def created(record):
    return response.created_response(db.public(record))


def tail(record, keys=("created_at", "updated_at", "version")):
    """Move the common system fields to the end of the payload."""
    for key in keys:
        if key in record:
            record[key] = record.pop(key)
    return record
