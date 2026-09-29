"""Response helpers that flush the pending version bumps first."""

from flask import request

import db
from errors import ApiError
from response import created_response, object_response, paginate


def ok(data):
    db.commit()
    return object_response(data)


def created(data):
    db.commit()
    return created_response(data)


def listing(rows):
    return paginate(rows)


def filtered(kind, spec):
    """spec maps query-parameter name -> row field name (exact match)."""
    rows = db.all_rows(kind)
    for param, field in spec.items():
        raw = request.args.get(param)
        if raw is not None:
            rows = [r for r in rows if r.get(field) == raw]
    return rows


def require(kind, row_id):
    row = db.get(kind, row_id)
    if row is None:
        raise ApiError(db.NOT_FOUND[kind])
    return row


def require_fk(kind, row_id):
    return require(kind, row_id)
