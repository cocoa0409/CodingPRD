"""Shared route plumbing: role gating, version flushing and envelope rendering."""

import functools

from flask import jsonify, request

import envelope
import ladder
import store


def endpoint(blueprint, rule, methods, roles):
    """Register a route that runs rung 1 and rung 2 before anything else, then
    flushes the request's version bumps before the response is serialized."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(**kwargs):
            caller = ladder.authenticate_and_authorize(roles)
            result = fn(caller, **kwargs)
            store.flush()
            body, status = envelope.render_result(result)
            return jsonify(body), status

        blueprint.add_url_rule(
            rule, endpoint=fn.__name__, view_func=wrapper, methods=methods
        )
        return wrapper

    return decorator


def query_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def apply_filter(rows, name, field=None):
    value = query_filter(name)
    if value is None:
        return rows
    key = field or name
    return [row for row in rows if row.get(key) == value]
