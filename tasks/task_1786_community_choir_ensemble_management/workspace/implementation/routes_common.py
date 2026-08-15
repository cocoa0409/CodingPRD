"""Route registration plumbing shared by all route modules."""

from envelope import list_response, object_response
from errors import ApiError

ROUTES = []


def route(method, path, roles, code=200):
    def decorator(fn):
        ROUTES.append({
            "method": method,
            "path": path,
            "roles": tuple(roles),
            "code": code,
            "fn": fn,
        })
        return fn
    return decorator


def one(view_fn, row, code=200):
    return object_response(view_fn(row), code)


def many(view_fn, rows, args):
    return list_response([view_fn(r) for r in rows], args)


def member_ownership_check(ctx, member_id):
    """PRD 2.8 tier 3: a Member caller may only touch their own resources."""
    if ctx["role"] == "Member" and member_id != ctx["uid"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", "Member callers may only touch their own resources")


def scope_member_filter(ctx, filters):
    """For member-owned collections: a Member caller sees only their own rows.
    An explicit member_id filter for someone else is an ownership violation."""
    if ctx["role"] != "Member":
        return filters
    requested = filters.get("member_id")
    if requested is not None and requested != ctx["uid"]:
        raise ApiError("ERR_FORBIDDEN_OWNERSHIP", "Member callers may only list their own resources")
    filters["member_id"] = ctx["uid"]
    return filters


def apply_filters(rows, filters):
    out = rows
    for key, value in filters.items():
        if value is not None:
            out = [r for r in out if r.get(key) == value]
    return out
