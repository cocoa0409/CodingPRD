"""Request-shape validation helpers (ERR_INVALID_REQUEST, PRD §2.10 lowest
priority) and pagination parsing (PRD §2.3).

These helpers raise ERR_INVALID_REQUEST (400) for: missing required field,
wrong type, enum value out of set, or number out of range.
"""
import errors

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _bad(msg):
    errors.fail(errors.ERR_INVALID_REQUEST, msg)


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        _bad("Request body must be a JSON object.")
    return body


def require(body, field):
    if field not in body or body[field] is None:
        _bad("Missing required field: %s" % field)
    return body[field]


def opt(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return body[field]


def as_int(value, field, minimum=None, maximum=None):
    # bool is a subclass of int; reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("Field %s must be an integer." % field)
    if minimum is not None and value < minimum:
        _bad("Field %s must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        _bad("Field %s must be <= %s." % (field, maximum))
    return value


def as_number(value, field, minimum=None, maximum=None,
              min_inclusive=True, max_inclusive=True):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("Field %s must be a number." % field)
    if minimum is not None:
        if min_inclusive and value < minimum:
            _bad("Field %s must be >= %s." % (field, minimum))
        if not min_inclusive and value <= minimum:
            _bad("Field %s must be > %s." % (field, minimum))
    if maximum is not None:
        if max_inclusive and value > maximum:
            _bad("Field %s must be <= %s." % (field, maximum))
        if not max_inclusive and value >= maximum:
            _bad("Field %s must be < %s." % (field, maximum))
    return value


def as_str(value, field, nonempty=True):
    if not isinstance(value, str):
        _bad("Field %s must be a string." % field)
    if nonempty and value == "":
        _bad("Field %s must be non-empty." % field)
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        _bad("Field %s must be a boolean." % field)
    return value


def as_enum(value, field, allowed):
    if value not in allowed:
        _bad("Field %s must be one of %s." % (field, sorted(allowed)))
    return value


def parse_pagination(args):
    """Parse limit/offset query params (PRD §2.3). Bad values -> 400."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            _bad("limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            _bad("limit must be between %d and %d." %
                 (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT))

    if offset_raw is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            _bad("offset must be an integer.")
        if offset < 0:
            _bad("offset must be >= 0.")

    return limit, offset


def paginate(items, limit, offset):
    """Slice a sorted list; return (page, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
