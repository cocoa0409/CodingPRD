"""Response envelope (PRD section 2.2) and the per-request commit hook."""
import functools
from datetime import datetime
from decimal import Decimal

from flask import g, jsonify

import store


class Res(object):
    __slots__ = ("data", "code", "kind", "extra_meta")

    def __init__(self, data, code=200, kind="object", extra_meta=None):
        self.data = data
        self.code = code
        self.kind = kind
        self.extra_meta = extra_meta


def one(record, code=200):
    return Res(record, code, "object")


def created(record):
    return Res(record, 201, "object")


def many(rows, page_meta):
    return Res(rows, 200, "array", page_meta)


def jsonable(value):
    if isinstance(value, datetime):
        return store.iso(value)
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return dict(
            (key, jsonable(item))
            for key, item in value.items()
            if not str(key).startswith("_")
        )
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def base_meta():
    return {
        "api_request_id": store.request_id(),
        "api_request_timestamp": store.iso(store.db.clock),
    }


def finalize(res):
    meta = base_meta()
    if res.extra_meta:
        meta.update(res.extra_meta)
    body = {"meta": meta, "response_type": res.kind, "data": jsonable(res.data)}
    return jsonify(body), res.code


def error_body(error_id, message):
    return {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def api(fn):
    """Route wrapper: resets the mutation registry, commits versions, serialises."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        g.touched = {}
        res = fn(*args, **kwargs)
        store.commit()
        if not isinstance(res, Res):
            res = Res(res if res is not None else {})
        return finalize(res)

    return wrapper
