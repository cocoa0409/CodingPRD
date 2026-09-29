"""Identity / role gate (PRD 2.1) and request-shape helpers (PRD 2.11 band 3)."""
from flask import request

from constants import ALL_ROLES
from errors import ApiError
from util import parse_dt


def authenticate(*allowed_roles):
    """Priority 1 then priority 2: headers first, then role authorization."""
    actor = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not actor or not str(actor).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return str(actor).strip(), role


def body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _bad(field, detail):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, detail))


def _present(payload, field, required):
    if field not in payload or payload[field] is None:
        if required:
            _bad(field, "is required")
        return False
    return True


def get_str(payload, field, required=True, min_len=1, max_len=None, default=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if len(value) < min_len:
        _bad(field, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(field, "must be at most %d characters" % max_len)
    return value


def get_int(payload, field, required=True, minimum=None, maximum=None, default=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(field, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be <= %s" % maximum)
    return value


def get_number(payload, field, required=True, minimum=None, exclusive_minimum=None,
               maximum=None, default=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(field, "must be a number")
    if minimum is not None and value < minimum:
        _bad(field, "must be >= %s" % minimum)
    if exclusive_minimum is not None and value <= exclusive_minimum:
        _bad(field, "must be > %s" % exclusive_minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be <= %s" % maximum)
    return value


def get_bool(payload, field, required=True, default=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def get_enum(payload, field, allowed, required=True, default=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if not isinstance(value, str) or value not in allowed:
        _bad(field, "must be one of %s" % ", ".join(allowed))
    return value


def get_dt(payload, field, required=True, default=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    try:
        return parse_dt(value)
    except Exception:
        _bad(field, "must be an ISO 8601 UTC timestamp")


def get_list(payload, field, required=True, default=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if not isinstance(value, list):
        _bad(field, "must be an array")
    return value


# ---------------------------------------------------------------- query params

def pagination_args():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None or limit == "":
        limit_value = 10
    else:
        try:
            limit_value = int(limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit_value < 1 or limit_value > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset is None or offset == "":
        offset_value = 0
    else:
        try:
            offset_value = int(offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset_value < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit_value, offset_value


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST",
                       "%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def query_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_int(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)


def query_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise ApiError("ERR_INVALID_REQUEST", "%s must be a boolean." % name)
