"""Auth (PRD §2.1), RBAC, body/query validation helpers (PRD §2.9)."""
import functools

from flask import g, request

from errors import err

ROLES = ("ProgramAdmin", "FleetManager", "Merchant", "FraudAnalyst", "TelematicsGateway")

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def authenticate():
    """Validation #1: X-User-ID and X-User-Role present, role recognized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_roles(*allowed):
    """Validation #1 then #2 (ERR_UNAUTHENTICATED -> ERR_UNAUTHORIZED)."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            _, role = authenticate()
            if role not in allowed:
                raise err("ERR_UNAUTHORIZED")
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def is_fleet_manager():
    return g.get("role") == "FleetManager"


def check_fleet(owning_account_id):
    """Validation #4: a FleetManager may only act on its own account's resources."""
    if is_fleet_manager() and owning_account_id != g.user_id:
        raise err("ERR_FORBIDDEN_FLEET")


# ---------------------------------------------------------------------------
# Body parsing / field validation  (ERR_VALIDATION, 400)
# ---------------------------------------------------------------------------

def body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_VALIDATION", "Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object.")
    return payload


def _bad(field, why):
    return err("ERR_VALIDATION", "Field '%s' %s." % (field, why))


def req_str(data, field):
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise _bad(field, "is required and must be a non-empty string")
    return value


def opt_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return req_str(data, field)


def req_int(data, field, minimum=None, maximum=None, exclusive_min=None):
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad(field, "is required and must be an integer")
    return _range(field, value, minimum, maximum, exclusive_min)


def opt_int(data, field, default=None, minimum=None, maximum=None, exclusive_min=None):
    if field not in data or data[field] is None:
        return default
    return req_int(data, field, minimum, maximum, exclusive_min)


def req_num(data, field, minimum=None, maximum=None, exclusive_min=None):
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _bad(field, "is required and must be a number")
    return _range(field, value, minimum, maximum, exclusive_min)


def opt_num(data, field, default=None, minimum=None, maximum=None, exclusive_min=None):
    if field not in data or data[field] is None:
        return default
    return req_num(data, field, minimum, maximum, exclusive_min)


def _range(field, value, minimum, maximum, exclusive_min):
    if minimum is not None and value < minimum:
        raise _bad(field, "must be >= %s" % minimum)
    if exclusive_min is not None and value <= exclusive_min:
        raise _bad(field, "must be > %s" % exclusive_min)
    if maximum is not None and value > maximum:
        raise _bad(field, "must be <= %s" % maximum)
    return value


def req_enum(data, field, choices):
    value = data.get(field)
    if not isinstance(value, str) or value not in choices:
        raise _bad(field, "must be one of %s" % (sorted(choices),))
    return value


def opt_enum(data, field, choices, default=None):
    if field not in data or data[field] is None:
        return default
    return req_enum(data, field, choices)


# ---------------------------------------------------------------------------
# Query params
# ---------------------------------------------------------------------------

def query_enum(field, choices):
    value = request.args.get(field)
    if value is None:
        return None
    if value not in choices:
        raise err("ERR_VALIDATION", "Query parameter '%s' must be one of %s." % (field, sorted(choices)))
    return value


def pagination():
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET

    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "Query parameter 'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise err("ERR_VALIDATION", "Query parameter 'limit' must be between %d and %d."
                      % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT))

    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise err("ERR_VALIDATION", "Query parameter 'offset' must be >= 0.")

    return limit, offset


def paginate(records):
    """Sort (created_at asc), page, and return (page_items, total_count, limit, offset)."""
    from db import sort_key

    limit, offset = pagination()
    ordered = sorted(records, key=sort_key)
    total = len(ordered)
    return ordered[offset:offset + limit], total, limit, offset
