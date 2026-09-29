"""Route registration helper: locking, auth, envelope."""

import functools

from errors import ApiError
from envelope import array_response, error_response, object_response
from auth import authenticate
from store import store


class ListResult(object):
    __slots__ = ("items", "pagination")

    def __init__(self, items, pagination):
        self.items = items
        self.pagination = pagination


def make_list(rows, limit, offset, serializer):
    total = len(rows)
    page = rows[offset:offset + limit]
    return ListResult(
        [serializer(r) for r in page],
        {
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": offset + len(page) < total,
        },
    )


def endpoint(app, rule, method, roles, code=200):
    def decorator(fn):
        @functools.wraps(fn)
        def view(**kwargs):
            with store.lock:
                try:
                    ctx = authenticate(roles)
                    result = fn(ctx, **kwargs)
                except ApiError as exc:
                    return error_response(exc.error_id, exc.message, exc.http_status)
                if isinstance(result, ListResult):
                    return array_response(result.items, result.pagination, code)
                return object_response(result, code)

        app.add_url_rule(
            rule,
            endpoint="%s.%s" % (fn.__module__, fn.__name__),
            view_func=view,
            methods=[method],
        )
        return fn

    return decorator
