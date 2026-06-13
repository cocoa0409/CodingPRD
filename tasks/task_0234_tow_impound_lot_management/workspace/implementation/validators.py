"""Body-validation helpers (validation priority 4: ERR_INVALID_REQUEST)."""
from errors import ApiError
from middleware import get_query_int
from response import array_response


def require_fields(body, names):
    for n in names:
        if body.get(n) is None:
            raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % n)


def require_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % name)
    return v


def require_int(body, name, minimum=None):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (name, minimum))
    return v


def optional_int(body, name, default=None, minimum=None):
    if name not in body or body.get(name) is None:
        return default
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (name, minimum))
    return v


def require_enum(body, name, choices):
    v = body.get(name)
    if v not in choices:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field %s must be one of %s" % (name, sorted(choices)))
    return v


def paginate_and_respond(items):
    """items already filtered + sorted by created_at ASC. Applies limit/offset."""
    limit = get_query_int("limit", 10, minimum=1, maximum=100)
    offset = get_query_int("offset", 0, minimum=0)
    total = len(items)
    page = items[offset:offset + limit]
    return array_response(page, limit, offset, total)


def sort_by_created(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
