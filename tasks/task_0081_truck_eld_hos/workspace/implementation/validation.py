"""Request body / pagination validation helpers (PRD §2.3, §2.9)."""
from flask import request

import errors

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def get_body():
    """Parse JSON body; tolerate empty body for no-input POSTs."""
    if request.data is None or len(request.data) == 0:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Malformed JSON body.")
    if not isinstance(data, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Body must be a JSON object.")
    return data


def get_pagination():
    """Return (limit, offset) validated; out-of-bounds -> ERR_INVALID_REQUEST."""
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "limit must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise errors.err(errors.ERR_INVALID_REQUEST, "limit out of bounds.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_INVALID_REQUEST, "offset must be an integer.")
        if offset < 0:
            raise errors.err(errors.ERR_INVALID_REQUEST, "offset out of bounds.")
    return limit, offset


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise errors.err(errors.ERR_INVALID_REQUEST, "Missing or invalid field: %s" % field)
    return v


def require_present(body, field):
    if field not in body:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    return body[field]


def enum_in(value, domain, field):
    if value not in domain:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "Field %s out of domain: %r" % (field, value))
    return value


def optional_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be a string." % field)
    return v


def require_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Field %s must be an integer." % field)
    return v
