"""Authentication, role authorisation, body-shape validation and pagination.

Header names, role names and pagination parameter names all come from PRD §2.1
and §2.3.
"""

import functools

from flask import g, request

import envelope
import store
from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLES = (
    "ProcurementOfficer",
    "ResponsibilityReviewer",
    "HearingOfficer",
    "DebarmentAuthority",
    "Vendor",
    "SystemAdmin",
)

ALL_ROLES = list(ROLES)


# --------------------------------------------------------------------------- #
# per-request mutation bookkeeping (PRD §2.4 and §2.9)
# --------------------------------------------------------------------------- #

def touch(row):
    """Mark a versioned row as mutated by this request.

    Each mutated row has its own updated_at refreshed and its own version
    incremented by exactly 1, however many times the request touched it.
    """
    if row is None:
        return row
    dirty = getattr(g, "dirty", None)
    if dirty is None:
        dirty = {}
        g.dirty = dirty
    dirty[id(row)] = row
    return row


def set_field(row, field, value):
    """Assign a field, marking the row mutated only when the value changed."""
    if row.get(field) != value:
        row[field] = value
        touch(row)
        return True
    return False


def finalize():
    for row in getattr(g, "dirty", {}).values():
        row["updated_at"] = store.now()
        row["version"] = row.get("version", 1) + 1


# --------------------------------------------------------------------------- #
# endpoint decorator
# --------------------------------------------------------------------------- #

def endpoint(roles):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            g.dirty = {}
            user_id = request.headers.get(USER_ID_HEADER)
            user_role = request.headers.get(USER_ROLE_HEADER)
            if not user_id or not user_role or user_role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if user_role not in roles:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            g.user_id = user_id
            g.user_role = user_role
            result = fn(*args, **kwargs)
            finalize()
            return render(result)

        return wrapper

    return decorator


def render(result):
    kind = result[0]
    if kind == "obj":
        _, row, serializer, status = result
        return envelope.object_response(serializer(row), status)
    if kind == "list":
        _, rows, serializer, limit, offset, total = result
        return envelope.list_response([serializer(r) for r in rows], limit, offset, total)
    if kind == "raw":
        _, data, status = result
        return envelope.object_response(data, status)
    raise RuntimeError("unknown handler result %r" % (kind,))


# --------------------------------------------------------------------------- #
# body shape helpers (PRD §2.10 step 3)
# --------------------------------------------------------------------------- #

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def _bad(field, why):
    return ApiError("ERR_INVALID_REQUEST", "field '%s' %s" % (field, why))


def req_str(data, field, min_len=1, max_len=None):
    if field not in data or data[field] is None:
        raise _bad(field, "is required")
    value = data[field]
    if not isinstance(value, str):
        raise _bad(field, "must be a string")
    if len(value) < min_len:
        raise _bad(field, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        raise _bad(field, "must be at most %d characters" % max_len)
    return value


def opt_str(data, field, default=None, min_len=1, max_len=None):
    if field not in data or data[field] is None:
        return default
    return req_str(data, field, min_len=min_len, max_len=max_len)


def req_int(data, field, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        raise _bad(field, "is required")
    return _as_int(data[field], field, minimum, maximum)


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        return default
    return _as_int(data[field], field, minimum, maximum)


def _as_int(value, field, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        raise _bad(field, "must be >= %d" % minimum)
    if maximum is not None and value > maximum:
        raise _bad(field, "must be <= %d" % maximum)
    return value


def req_bool(data, field):
    if field not in data or data[field] is None:
        raise _bad(field, "is required")
    if not isinstance(data[field], bool):
        raise _bad(field, "must be a boolean")
    return data[field]


def opt_bool(data, field, default=False):
    if field not in data or data[field] is None:
        return default
    if not isinstance(data[field], bool):
        raise _bad(field, "must be a boolean")
    return data[field]


def req_enum(data, field, allowed):
    value = req_str(data, field)
    if value not in allowed:
        raise _bad(field, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def opt_enum(data, field, allowed, default=None):
    if field not in data or data[field] is None:
        return default
    return req_enum(data, field, allowed)


def req_dt(data, field):
    from util import parse_dt
    value = req_str(data, field)
    try:
        return parse_dt(value)
    except Exception:
        raise _bad(field, "must be an ISO 8601 instant")


def opt_dt(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return req_dt(data, field)


def req_array(data, field, non_empty=True):
    if field not in data or data[field] is None:
        raise _bad(field, "is required")
    value = data[field]
    if not isinstance(value, list):
        raise _bad(field, "must be an array")
    if non_empty and not value:
        raise _bad(field, "must be non-empty")
    return value


def opt_array(data, field, default=None, non_empty=False):
    if field not in data or data[field] is None:
        return list(default) if default is not None else []
    return req_array(data, field, non_empty=non_empty)


def code_array(data, field, allowed, required=False, non_empty=False, default=None):
    """An array of enum codes. Shape errors surface as ERR_INVALID_REQUEST;
    the distinctness rule is a separate check (PRD §2.10 step 4)."""
    if required:
        items = req_array(data, field, non_empty=non_empty)
    else:
        if field not in data or data[field] is None:
            return list(default) if default is not None else []
        items = req_array(data, field, non_empty=non_empty)
    for item in items:
        if not isinstance(item, str) or item not in allowed:
            raise _bad(field, "members must be one of %s" % ", ".join(sorted(allowed)))
    return items


def int_array(data, field, default=None):
    if field not in data or data[field] is None:
        return list(default) if default is not None else []
    items = req_array(data, field, non_empty=False)
    out = []
    for item in items:
        if isinstance(item, bool) or not isinstance(item, int):
            raise _bad(field, "members must be integers")
        out.append(item)
    return out


def str_array(data, field, default=None):
    if field not in data or data[field] is None:
        return list(default) if default is not None else []
    items = req_array(data, field, non_empty=False)
    for item in items:
        if not isinstance(item, str):
            raise _bad(field, "members must be strings")
    return items


def distinct(items, field):
    if len(set(items)) != len(items):
        raise ApiError(
            "ERR_DUPLICATE_FACTOR_CODE",
            "'%s' contains a repeated member" % field,
        )
    return items


# --------------------------------------------------------------------------- #
# query parameters
# --------------------------------------------------------------------------- #

def pagination():
    """PRD §2.3: limit defaults to 10 (1..100); offset defaults to 0 (min 0)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "'limit' must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "'offset' must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "'offset' must be >= 0")
    return limit, offset


def query(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_bool(name, default=False):
    value = query(name)
    if value is None:
        return default
    lowered = value.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    raise ApiError("ERR_INVALID_REQUEST", "'%s' must be a boolean" % name)


def query_dt(name):
    from util import parse_dt
    value = query(name)
    if value is None:
        return None
    try:
        return parse_dt(value)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "'%s' must be an ISO 8601 instant" % name)


def paginate(rows, limit, offset):
    total = len(rows)
    if offset > total:
        return [], total
    return rows[offset:offset + limit], total


def match_filters(row, filters):
    for field, expected in filters.items():
        if expected is None:
            continue
        if row.get(field) != expected:
            return False
    return True
