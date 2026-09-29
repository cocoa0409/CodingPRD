"""Request field parsing / well-formedness checks (rejection ladder rung 3)."""
import datetime

from errors import ApiError

MISSING = object()


def bad(msg="Malformed request."):
    return ApiError("ERR_INVALID_REQUEST", msg)


def body_of(req):
    if req.method in ("POST", "PATCH", "PUT"):
        try:
            data = req.get_json(force=True, silent=True)
        except Exception:
            raise bad()
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise bad("Request body must be a JSON object.")
        return data
    return {}


def _present(body, key):
    return key in body and body[key] is not None


def req_str(body, key):
    if not _present(body, key):
        raise bad("Missing required field '%s'." % key)
    v = body[key]
    if not isinstance(v, str) or v == "":
        raise bad("Field '%s' must be a non-empty string." % key)
    return v


def opt_str(body, key, default=None):
    if not _present(body, key):
        return default
    v = body[key]
    if not isinstance(v, str):
        raise bad("Field '%s' must be a string." % key)
    return v


def req_enum(body, key, allowed):
    v = req_str(body, key)
    if v not in allowed:
        raise bad("Field '%s' must be one of %s." % (key, ", ".join(sorted(allowed))))
    return v


def opt_enum(body, key, allowed, default=None):
    if not _present(body, key):
        return default
    return req_enum(body, key, allowed)


def _as_int(key, v, minimum=None, maximum=None):
    if isinstance(v, bool) or not isinstance(v, int):
        raise bad("Field '%s' must be an integer." % key)
    if minimum is not None and v < minimum:
        raise bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and v > maximum:
        raise bad("Field '%s' must be <= %s." % (key, maximum))
    return v


def req_int(body, key, minimum=None, maximum=None):
    if not _present(body, key):
        raise bad("Missing required field '%s'." % key)
    return _as_int(key, body[key], minimum, maximum)


def opt_int(body, key, default=None, minimum=None, maximum=None):
    if not _present(body, key):
        return default
    return _as_int(key, body[key], minimum, maximum)


def _as_num(key, v, minimum=None):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise bad("Field '%s' must be a number." % key)
    if minimum is not None and v < minimum:
        raise bad("Field '%s' must be >= %s." % (key, minimum))
    return v


def req_num(body, key, minimum=None):
    if not _present(body, key):
        raise bad("Missing required field '%s'." % key)
    return _as_num(key, body[key], minimum)


def opt_num(body, key, default=None, minimum=None):
    if not _present(body, key):
        return default
    return _as_num(key, body[key], minimum)


def req_bool(body, key):
    if not _present(body, key):
        raise bad("Missing required field '%s'." % key)
    v = body[key]
    if not isinstance(v, bool):
        raise bad("Field '%s' must be a boolean." % key)
    return v


def opt_bool(body, key, default=None):
    if not _present(body, key):
        return default
    v = body[key]
    if not isinstance(v, bool):
        raise bad("Field '%s' must be a boolean." % key)
    return v


def parse_date(key, v):
    if not isinstance(v, str):
        raise bad("Field '%s' must be an ISO 8601 date." % key)
    try:
        return datetime.date.fromisoformat(v)
    except Exception:
        raise bad("Field '%s' must be an ISO 8601 date." % key)


def req_date(body, key):
    if not _present(body, key):
        raise bad("Missing required field '%s'." % key)
    return parse_date(key, body[key])


def opt_date(body, key, default=None):
    if not _present(body, key):
        return default
    return parse_date(key, body[key])


def date_str(d):
    return d.isoformat() if d is not None else None


def pagination(args):
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(str(raw))
        except Exception:
            raise bad("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise bad("limit must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(str(raw))
        except Exception:
            raise bad("offset must be an integer.")
        if offset < 0:
            raise bad("offset must be >= 0.")
    return limit, offset


def query_enum(args, key, allowed):
    v = args.get(key)
    if v is None or v == "":
        return None
    if v not in allowed:
        raise bad("Query parameter '%s' must be one of %s." % (key, ", ".join(sorted(allowed))))
    return v


def query_bool(args, key):
    v = args.get(key)
    if v is None or v == "":
        return None
    low = str(v).lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    raise bad("Query parameter '%s' must be a boolean." % key)


def query_int(args, key):
    v = args.get(key)
    if v is None or v == "":
        return None
    try:
        return int(str(v))
    except Exception:
        raise bad("Query parameter '%s' must be an integer." % key)
