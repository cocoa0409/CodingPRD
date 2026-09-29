"""Request boundary: one process-wide lock per request, one error envelope."""

import functools

from flask import g

from db import DB
from errors import ApiError
from response import error_response


def api(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        # A single non-nesting lock guards every handler.  No handler acquires a
        # second lock, so the store cannot deadlock under concurrent requests.
        with DB.lock:
            g._touched_ids = set()
            try:
                return fn(*args, **kwargs)
            except ApiError as err:
                return error_response(err)

    return wrapper
