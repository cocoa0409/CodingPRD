"""Shared route helpers: path/body resolution and list filtering."""

from flask import request

import db
import errors
import response
from errors import fail

PREFIX = "/supplement-compliance"


def path_row(collection, row_id, error_id):
    """Screen 3: the row named by the endpoint's single path identifier must exist."""
    row = db.get(collection, row_id)
    if row is None:
        fail(error_id, "No such resource: %s." % row_id)
    return row


def fk_row(collection, row_id, error_id):
    """Screen 5: a foreign key arriving in the body must resolve, in input order."""
    row = db.get(collection, row_id)
    if row is None:
        fail(error_id, "No such referenced resource: %s." % row_id)
    return row


def _as_bool(raw):
    if raw is None:
        return None
    text = raw.strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    return None


def listing(collection, serializer, filters=(), bool_filters=(), int_filters=()):
    """Ordered by created_at ascending, filtered conjunctively, then paginated."""
    rows = db.all_rows(collection)

    for name in filters:
        raw = request.args.get(name)
        if raw is None:
            continue
        rows = [r for r in rows if r.get(name) == raw]

    for name in bool_filters:
        raw = request.args.get(name)
        if raw is None:
            continue
        wanted = _as_bool(raw)
        if wanted is None:
            fail(errors.ERR_VALIDATION, "%s must be a boolean." % name)
        rows = [r for r in rows if r.get(name) is wanted]

    for name in int_filters:
        raw = request.args.get(name)
        if raw is None:
            continue
        try:
            wanted = int(raw)
        except (TypeError, ValueError):
            fail(errors.ERR_VALIDATION, "%s must be an integer." % name)
        rows = [r for r in rows if r.get(name) == wanted]

    return response.paginate(rows, serializer)
