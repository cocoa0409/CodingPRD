"""Request body / pagination validation helpers (priority 5, pagination)."""
from flask import request

from errors import err, ERR_INVALID_REQUEST, ERR_VALIDATION_PAGINATION


def get_json_body():
    """Parse JSON body, defaulting to {} for empty/absent bodies."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "Malformed JSON body.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return body


def require_string(body, field):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: %s." % field)
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise err(ERR_INVALID_REQUEST, "Field %s must be a non-empty string." % field)
    return val


def optional_string(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise err(ERR_INVALID_REQUEST, "Field %s must be a non-empty string." % field)
    return val


def require_enum(body, field, domain):
    val = require_string(body, field)
    if val not in domain:
        raise err(ERR_INVALID_REQUEST, "Field %s is out of domain." % field)
    return val


def optional_enum(body, field, domain, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in domain:
        raise err(ERR_INVALID_REQUEST, "Field %s is out of domain." % field)
    return val


def _is_number(val):
    return isinstance(val, (int, float)) and not isinstance(val, bool)


def require_number(body, field, positive=False, non_negative=False):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: %s." % field)
    val = body[field]
    if not _is_number(val):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a number." % field)
    if positive and val <= 0:
        raise err(ERR_INVALID_REQUEST, "Field %s must be strictly positive." % field)
    if non_negative and val < 0:
        raise err(ERR_INVALID_REQUEST, "Field %s must be zero or greater." % field)
    return val


def optional_number(body, field, positive=False, non_negative=False, default=None):
    if field not in body or body[field] is None:
        return default
    return require_number(body, field, positive=positive, non_negative=non_negative)


def require_int(body, field, minimum=None, non_negative=False):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: %s." % field)
    val = body[field]
    if not isinstance(val, int) or isinstance(val, bool):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer." % field)
    if non_negative and val < 0:
        raise err(ERR_INVALID_REQUEST, "Field %s must be zero or greater." % field)
    if minimum is not None and val < minimum:
        raise err(ERR_INVALID_REQUEST, "Field %s must be >= %d." % (field, minimum))
    return val


def optional_int(body, field, minimum=None, non_negative=False, default=None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, minimum=minimum, non_negative=non_negative)


def parse_pagination():
    """limit default 10 (1..100); offset default 0 (>=0). Out of bounds ->
    ERR_VALIDATION_PAGINATION."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err(ERR_VALIDATION_PAGINATION, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err(ERR_VALIDATION_PAGINATION, "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err(ERR_VALIDATION_PAGINATION, "offset must be an integer.")
        if offset < 0:
            raise err(ERR_VALIDATION_PAGINATION, "offset must be zero or greater.")
    return limit, offset


def paginate(items, limit, offset):
    """Slice an already-sorted list and return (page, total_count)."""
    total = len(items)
    return items[offset:offset + limit], total
