"""Schema-level request validation (PRD §2.5 / §1.4 priority 18).

Required fields present, enums valid, numbers in range -> else ERR_INVALID_REQUEST
(HTTP 400). This is enforced as the body is parsed, before business rules.
"""
import numbers

from flask import request

from errors import invalid_request, ERR_INVALID_REQUEST, ApiError


def get_json_body():
    """Return the parsed JSON body as a dict. Missing/empty body is treated as
    {} so that endpoints with all-optional inputs work; a non-object JSON body
    is a schema error."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise invalid_request("Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise invalid_request("Request body must be a JSON object.")
    return body


def require(body, field):
    if field not in body or body[field] is None:
        raise invalid_request("Missing required field: {}.".format(field))
    return body[field]


def opt(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return body[field]


def as_str(value, field, min_len=None, max_len=None):
    if not isinstance(value, str):
        raise invalid_request("{} must be a string.".format(field))
    if min_len is not None and len(value) < min_len:
        raise invalid_request("{} must be at least {} characters.".format(field, min_len))
    if max_len is not None and len(value) > max_len:
        raise invalid_request("{} must be at most {} characters.".format(field, max_len))
    return value


def as_number(value, field, gt=None, ge=None, le=None):
    if isinstance(value, bool) or not isinstance(value, numbers.Number):
        raise invalid_request("{} must be a number.".format(field))
    v = float(value)
    if gt is not None and not (v > gt):
        raise invalid_request("{} must be greater than {}.".format(field, gt))
    if ge is not None and not (v >= ge):
        raise invalid_request("{} must be at least {}.".format(field, ge))
    if le is not None and not (v <= le):
        raise invalid_request("{} must be at most {}.".format(field, le))
    return value


def as_int(value, field, gt=None, ge=None, le=None):
    if isinstance(value, bool):
        raise invalid_request("{} must be an integer.".format(field))
    if isinstance(value, float):
        if not value.is_integer():
            raise invalid_request("{} must be an integer.".format(field))
        value = int(value)
    if not isinstance(value, int):
        raise invalid_request("{} must be an integer.".format(field))
    if gt is not None and not (value > gt):
        raise invalid_request("{} must be greater than {}.".format(field, gt))
    if ge is not None and not (value >= ge):
        raise invalid_request("{} must be at least {}.".format(field, ge))
    if le is not None and not (value <= le):
        raise invalid_request("{} must be at most {}.".format(field, le))
    return value


def as_enum(value, field, choices):
    if not isinstance(value, str) or value not in choices:
        raise invalid_request("{} must be one of {}.".format(field, sorted(choices)))
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise invalid_request("{} must be a boolean.".format(field))
    return value


# ---- Pagination (PRD §2.3; SCAFFOLD pagination_defaults limit=10 min=1 max=100 offset=0)

def parse_pagination():
    limit = _parse_int_param("limit", default=10, min_v=1, max_v=100)
    offset = _parse_int_param("offset", default=0, min_v=0, max_v=None)
    return limit, offset


def _parse_int_param(name, default, min_v, max_v):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (ValueError, TypeError):
        raise invalid_request("{} must be an integer.".format(name))
    if min_v is not None and val < min_v:
        raise invalid_request("{} must be at least {}.".format(name, min_v))
    if max_v is not None and val > max_v:
        raise invalid_request("{} must be at most {}.".format(name, max_v))
    return val


def paginate(records, limit, offset):
    """Sort by creation order (created_at ASC, ties broken by _seq) and slice."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


def parse_bool_param(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    low = raw.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    raise invalid_request("{} must be a boolean.".format(name))
