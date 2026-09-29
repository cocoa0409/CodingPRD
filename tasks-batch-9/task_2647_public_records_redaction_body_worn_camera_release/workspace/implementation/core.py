"""Endpoint decorators: locking, auth, atomicity, reconciliation, versioning."""
import functools

from flask import jsonify

from db import LOCK, store
from errors import ApiError, fail
from middleware import authenticate, authorize
from reconcile import reconcile_all
from response import ListResult, error_response, list_response, object_response
from serialize import dump

# Fields excluded from the mutation diff: the bookkeeping fields themselves and
# every internal key.
_BOOKKEEPING = ("version", "updated_at")


class Raw(object):
    """Wrapper for a handler result that is not an entity projection."""

    def __init__(self, data):
        self.data = data


def _projection(row):
    return {key: value for key, value in row.items()
            if key not in _BOOKKEEPING and not key.startswith("_")}


def apply_versions(before, ctx):
    """Bump version/updated_at on every pre-existing row whose fields changed."""
    stamp = store.now_str()
    for name, rows in store.data.items():
        prior_rows = before.get(name, {})
        for row_id, row in rows.items():
            if "version" not in row:
                continue  # append-only ledger entries carry neither field
            prior = prior_rows.get(row_id)
            if prior is None:
                continue  # created by this call: already at version 1
            forced = (name, row_id) in ctx.force_bump
            if forced or _projection(prior) != _projection(row):
                row["version"] = row["version"] + 1
                row["updated_at"] = stamp


def must_get(collection, row_id, error_id):
    row = store.get(collection, row_id)
    if row is None:
        fail(error_id, "%s %r not found" % (collection, row_id))
    return row


def _render(result, code):
    if isinstance(result, Raw):
        return jsonify(object_response(result.data)), code
    if isinstance(result, ListResult):
        result.rows = [dump(row) for row in result.rows]
        return jsonify(list_response(result)), code
    return jsonify(object_response(dump(result))), code


def write_endpoint(roles, code=200):
    """A mutating endpoint: atomic, reconciled and version-bumped."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(**kwargs):
            with LOCK:
                snap = store.snapshot()
                try:
                    ctx = authenticate()
                    ctx.mutating = True
                    authorize(ctx, roles)
                    result = fn(ctx, **kwargs)
                    reconcile_all()
                    apply_versions(snap[0], ctx)
                except ApiError as err:
                    store.restore(snap)
                    return jsonify(error_response(err.error_id, err.message)), \
                        err.http_status
                except Exception:
                    store.restore(snap)
                    raise
                return _render(result, code)

        return wrapper

    return decorator


def read_endpoint(roles):
    """A read-only endpoint: never reconciles and never bumps a version."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(**kwargs):
            with LOCK:
                try:
                    ctx = authenticate()
                    authorize(ctx, roles)
                    result = fn(ctx, **kwargs)
                except ApiError as err:
                    return jsonify(error_response(err.error_id, err.message)), \
                        err.http_status
                return _render(result, 200)

        return wrapper

    return decorator
