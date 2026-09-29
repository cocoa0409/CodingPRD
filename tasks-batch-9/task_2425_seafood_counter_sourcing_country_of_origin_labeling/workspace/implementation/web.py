"""Flask application object, request plumbing and list helpers."""

import functools

from flask import Flask, g, jsonify, request

from auth import authenticate
from common import commit
from envelope import build_meta, paginate, render_error, render_result
from errors import ApiError, fail
from store import db

API = "/seafood-ops"

app = Flask(__name__)
app.url_map.strict_slashes = False


def body_json():
    """Parse the request body.  A missing or malformed body is treated as an
    empty object so that the 404 existence checks of PRD 2.9 (items 6-18) still
    precede ERR_INVALID_REQUEST (item 19)."""
    data = request.get_json(silent=True, force=True)
    if not isinstance(data, dict):
        return {}
    return data


def route(rule, methods=("POST",), roles=()):
    def decorator(fn):
        @app.route(API + rule, methods=list(methods), endpoint=fn.__name__)
        @functools.wraps(fn)
        def wrapper(**kwargs):
            with db.lock:
                g.dirty = {}
                g.created = set()
                try:
                    authenticate(roles)
                    result = fn(body_json(), **kwargs)
                    commit()
                    return render_result(result)
                except ApiError as error:
                    return render_error(error)

        return fn

    return decorator


# --------------------------------------------------------------------------
# list helpers
# --------------------------------------------------------------------------

def string_filter(items, field, value):
    if value is None:
        return items
    return [item for item in items if item.get(field) == value]


def int_filter(items, field, value):
    if value is None:
        return items
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return []
    return [item for item in items if item.get(field) == parsed]


def bool_filter(items, field, value):
    if value is None:
        return items
    lowered = str(value).strip().lower()
    if lowered in ("true", "1"):
        parsed = True
    elif lowered in ("false", "0"):
        parsed = False
    else:
        return []
    return [item for item in items if item.get(field) is parsed]


def listing(serializer, items, string_fields=(), int_fields=(), bool_fields=()):
    args = request.args
    for field in string_fields:
        items = string_filter(items, field, args.get(field))
    for field in int_fields:
        items = int_filter(items, field, args.get(field))
    for field in bool_fields:
        items = bool_filter(items, field, args.get(field))
    from common import sort_records

    return paginate(serializer, sort_records(items), args)


# --------------------------------------------------------------------------
# framework-level error handling: keep the envelope shape everywhere
# --------------------------------------------------------------------------

def _envelope_error(error_id, message, status):
    body = {
        "meta": build_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


@app.errorhandler(404)
def _handle_404(_error):
    return _envelope_error("ERR_INVALID_REQUEST", "Unknown resource path.", 404)


@app.errorhandler(405)
def _handle_405(_error):
    return _envelope_error("ERR_INVALID_REQUEST", "Method not allowed for this path.", 405)


@app.errorhandler(400)
def _handle_400(_error):
    return _envelope_error("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)


@app.errorhandler(Exception)
def _handle_unexpected(error):
    if isinstance(error, ApiError):
        return render_error(error)
    app.logger.exception("unhandled error")
    return _envelope_error("ERR_INVALID_REQUEST", "Unexpected server error: %s" % error, 400)
