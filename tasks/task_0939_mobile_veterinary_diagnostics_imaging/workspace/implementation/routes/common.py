"""Shared plumbing for the route modules."""

from core import db, envelope
from core.errors import ApiError
from core.validate import pagination
from services import serialize


def need(collection, key, error_id):
    """Rung 4 existence check for one identifier.

    Loading a Study also runs the turnaround breach test: PRD 3.8 says breach is
    evaluated on EVERY read of a study and after every mutation of it, so a study
    that silently breached while the clock moved must already read as BREACHED by
    the time rung 20 inspects its `tat_status`.
    """
    row = db.get(collection, key)
    if row is None:
        raise ApiError(error_id)
    if collection == "studies":
        from services import tat

        tat.evaluate(row)
    return row


def fk(data, field, collection, error_id):
    """Rung 4 for a body foreign key.

    A well-formed identifier that names nothing raises its 404 code here; a
    missing or mistyped value is left for rung 5's ERR_VALIDATION.
    """
    value = data.get(field)
    if isinstance(value, str) and value:
        row = db.get(collection, value)
        if row is None:
            raise ApiError(error_id)
        if collection == "studies":
            from services import tat

            tat.evaluate(row)
        return row
    return None


def one(collection, row, status=200):
    return envelope.object_response(serialize.SERIALIZERS[collection](row), status)


def listing(collection, rows):
    limit, offset = pagination()
    items, total = serialize.paged(collection, rows, limit, offset)
    return envelope.array_response(items, limit, offset, total)


def apply_filters(rows, spec):
    """`spec` maps a query-parameter name to the record field it filters on.

    Filters never error: an unrecognised value simply matches nothing (see the
    deliberate-exclusion list in core/validate.py).
    """
    from flask import request

    out = rows
    for param, field in spec.items():
        if param not in request.args:
            continue
        wanted = request.args.get(param)
        out = [r for r in out if str(r.get(field)) == wanted]
    return out


def apply_derived_filter(rows, param, fn):
    from flask import request

    if param not in request.args:
        return rows
    wanted = request.args.get(param)
    return [r for r in rows if fn(r) == wanted]
