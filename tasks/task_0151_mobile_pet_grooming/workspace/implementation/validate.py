"""Body validation helpers. Malformed body -> ERR_INVALID_REQUEST (422)."""
from errors import err, ERR_INVALID_REQUEST


def require_body(data):
    if data is None or not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_field(data, name):
    if name not in data or data[name] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % name)
    return data[name]


def opt_field(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return data[name]


def require_str(data, name):
    v = require_field(data, name)
    if not isinstance(v, str) or v == "":
        raise err(ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % name)
    return v


def require_enum(data, name, allowed):
    v = require_str(data, name)
    if v not in allowed:
        raise err(ERR_INVALID_REQUEST, "Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def opt_enum(data, name, allowed, default):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, str) or v not in allowed:
        raise err(ERR_INVALID_REQUEST, "Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require_int(data, name, minimum=None, maximum=None):
    v = require_field(data, name)
    if not _is_int(v):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        raise err(ERR_INVALID_REQUEST, "Field %s must be >= %s" % (name, minimum))
    if maximum is not None and v > maximum:
        raise err(ERR_INVALID_REQUEST, "Field %s must be <= %s" % (name, maximum))
    return v


def require_number(data, name, minimum=None, maximum=None, exclusive_min=None):
    v = require_field(data, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a number" % name)
    if minimum is not None and v < minimum:
        raise err(ERR_INVALID_REQUEST, "Field %s must be >= %s" % (name, minimum))
    if maximum is not None and v > maximum:
        raise err(ERR_INVALID_REQUEST, "Field %s must be <= %s" % (name, maximum))
    if exclusive_min is not None and v <= exclusive_min:
        raise err(ERR_INVALID_REQUEST, "Field %s must be > %s" % (name, exclusive_min))
    return v


def opt_number(data, name, default, minimum=None, maximum=None):
    if name not in data or data[name] is None:
        return default
    return require_number(data, name, minimum=minimum, maximum=maximum)


def require_bool(data, name):
    v = require_field(data, name)
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a boolean" % name)
    return v


def opt_bool(data, name, default):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, bool):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a boolean" % name)
    return v


def require_zip(data, name):
    v = require_str(data, name)
    if len(v) != 5 or not v.isdigit():
        raise err(ERR_INVALID_REQUEST, "Field %s must be exactly 5 digits" % name)
    return v


def parse_pagination(args):
    """Read limit/offset from query args. Out-of-range -> ERR_INVALID_REQUEST."""
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ASC (then id for determinism), then slice."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
