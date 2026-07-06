"""Request validation helpers (PRD §2.3, §2.9, §2.10; SCAFFOLD validations).

These enforce the structural-check precedence AFTER auth/existence/FK:
  ERR_INVALID_REQUEST (400)   — malformed body / missing required / wrong type
  ERR_INVALID_ENUM    (422)   — enum field outside its declared set
  ERR_VALUE_OUT_OF_RANGE (422)— numeric field out of range / depart >= return
  ERR_INVALID_PAGINATION (400)— limit outside [1,100] or offset < 0
"""
from flask import request
import errors

# Enum value sets (PRD §2.10) — fixed and stored/returned verbatim.
THEME_VALUES = {"WINE", "BREWERY", "FOOD", "MIXED"}
VENUE_KIND_VALUES = {"WINERY", "BREWERY", "RESTAURANT"}
VEHICLE_STATUS_VALUES = {"AVAILABLE", "OUT_OF_SERVICE"}
PARTNER_STATUS_VALUES = {"ACTIVE", "SUSPENDED"}


def get_json_body():
    """Return the parsed JSON object body, or {} for an empty body.

    A present-but-malformed body (not a JSON object) -> ERR_INVALID_REQUEST.
    """
    if request.content_length in (None, 0) and not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % f)


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or val == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % field)
    return val


def opt_str(body, field):
    if field not in body or body[field] is None:
        return None
    val = body[field]
    if not isinstance(val, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be a string" % field)
    return val


def require_int(body, field):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    return val


def opt_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    return val


def require_number(body, field):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be a number" % field)
    return val


def opt_number(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be a number" % field)
    return val


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be a boolean" % field)
    return val


def check_enum(value, allowed, field):
    if value not in allowed:
        raise errors.err(errors.ERR_INVALID_ENUM, "Field %s has an invalid value: %r" % (field, value))


def out_of_range():
    raise errors.err(errors.ERR_VALUE_OUT_OF_RANGE, "Numeric value out of permitted range")


def parse_pagination():
    """Read limit/offset query params with defaults (PRD §2.3).

    limit defaults to 10, min 1, max 100. offset defaults to 0, min 0.
    Out-of-range -> ERR_INVALID_PAGINATION.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_INVALID_PAGINATION, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.err(errors.ERR_INVALID_PAGINATION, "limit must be in [1,100]")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_INVALID_PAGINATION, "offset must be an integer")
        if offset < 0:
            raise errors.err(errors.ERR_INVALID_PAGINATION, "offset must be >= 0")

    return limit, offset


def paginate(records, limit, offset, serializer):
    """Sort by creation order ascending (PRD §2.3), apply window, serialize."""
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return [serializer(r) for r in window], total
