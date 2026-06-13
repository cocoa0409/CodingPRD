"""Request-body parsing, pagination, field validation, and serialization."""

from flask import request

import errors
from clock import parse_iso
from errors import err


def get_body():
    """Return the JSON body as a dict, or {} when absent. Malformed JSON -> 422."""
    if request.data is None or len(request.data) == 0:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        # Empty/absent body is acceptable for action endpoints with optional
        # fields; only genuinely malformed JSON content lands here.
        if request.data and request.data.strip():
            raise err(errors.ERR_INVALID_REQUEST, "Malformed JSON body")
        return {}
    if not isinstance(body, dict):
        raise err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


# --------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# --------------------------------------------------------------------------
def get_pagination():
    limit = _parse_int_param("limit", default=10)
    offset = _parse_int_param("offset", default=0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _parse_int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def paginate(records, limit, offset):
    """Sort by created_at ascending (stable by insertion seq) and slice."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total


# --------------------------------------------------------------------------
# Field validation primitives (priority 5: ERR_INVALID_REQUEST, 422).
# --------------------------------------------------------------------------
def require_fields(body, names):
    for name in names:
        if name not in body or body[name] is None:
            raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")


def require_str(body, name):
    val = body.get(name)
    if not isinstance(val, str) or val == "":
        raise err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string")
    return val


def require_fk(body, name):
    """Extract a foreign-key id field for existence checking (priority 4).

    A missing/non-string FK is a well-formedness failure (priority 5, 422); a
    present-and-valid id that resolves to nothing is the caller's job to 404 via
    the matching lookup. This lets FK-existence (404) be evaluated before the
    rest of the body's well-formedness (422), per PRD §3.9.
    """
    val = body.get(name)
    if not isinstance(val, str) or val == "":
        raise err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string")
    return val


def require_state_code(body, name):
    val = body.get(name)
    if not isinstance(val, str) or len(val) != 2 or not val.isalpha():
        raise err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a two-letter state code")
    return val


def require_int(body, name, minimum=None):
    val = body.get(name)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    if minimum is not None and val < minimum:
        raise err(errors.ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}")
    return val


def optional_int(body, name, default, minimum=None):
    if name not in body or body[name] is None:
        return default
    return require_int(body, name, minimum=minimum)


def require_number(body, name, minimum=None):
    val = body.get(name)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err(errors.ERR_INVALID_REQUEST, f"Field {name} must be a number")
    if minimum is not None and val < minimum:
        raise err(errors.ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}")
    return val


def require_enum(body, name, allowed):
    val = body.get(name)
    if val not in allowed:
        raise err(errors.ERR_INVALID_REQUEST,
                  f"Field {name} must be one of {sorted(allowed)}")
    return val


def optional_enum(body, name, allowed, default):
    if name not in body or body[name] is None:
        return default
    return require_enum(body, name, allowed)


def require_datetime(body, name):
    val = body.get(name)
    dt = parse_iso(val)
    if dt is None:
        raise err(errors.ERR_INVALID_REQUEST, f"Field {name} must be an ISO 8601 instant")
    return dt
