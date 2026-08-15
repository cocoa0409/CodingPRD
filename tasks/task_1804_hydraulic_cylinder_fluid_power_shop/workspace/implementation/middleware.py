"""Auth header extraction, role checking, request-body shape validation, and
pagination parsing. Validation order per PRD 2.9:
  1. request shape -> ERR_INVALID_REQUEST (runs first on every endpoint)
  2. authentication -> ERR_UNAUTHENTICATED
  3. role permission -> ERR_FORBIDDEN
  4. ownership -> ERR_NOT_OWNER   (enforced inside each handler)
  5. existence -> ERR_NOT_FOUND   (enforced inside each handler)
"""

from flask import request

from db import parse_iso8601
from errors import (
    err_invalid_request,
    err_unauthenticated,
    err_forbidden,
)

ROLES = ["ShopAdmin", "ServiceAdvisor", "Technician", "QualityInspector", "Customer"]

ALL_ROLES = tuple(ROLES)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class Actor:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def require_auth():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err_unauthenticated()
    return Actor(user_id, role)


def require_role(actor, allowed):
    if actor.role not in allowed:
        raise err_forbidden()


# ---------------------------------------------------------------------------
# Body shape validation
# ---------------------------------------------------------------------------

# Field kinds used in endpoint specs:
#   ("string" | "integer" | "number" | "boolean" | "datetime" | "array" | "object", required, nullable)
#   ("enum", required, nullable, values)
#   ("enum_array", required, nullable, values, non_empty)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v):
    return (isinstance(v, int) or isinstance(v, float)) and not isinstance(v, bool)


def _check_value(name, value, spec):
    kind = spec[0]
    nullable = spec[2] if len(spec) > 2 else False
    if value is None:
        if nullable:
            return
        raise err_invalid_request("Field '%s' must not be null" % name)
    if kind == "string":
        if not isinstance(value, str):
            raise err_invalid_request("Field '%s' must be a string" % name)
    elif kind == "integer":
        if not _is_int(value):
            raise err_invalid_request("Field '%s' must be an integer" % name)
    elif kind == "number":
        if not _is_number(value):
            raise err_invalid_request("Field '%s' must be a number" % name)
    elif kind == "boolean":
        if not isinstance(value, bool):
            raise err_invalid_request("Field '%s' must be a boolean" % name)
    elif kind == "datetime":
        if not isinstance(value, str):
            raise err_invalid_request("Field '%s' must be an ISO 8601 string" % name)
        try:
            parse_iso8601(value)
        except Exception:
            raise err_invalid_request("Field '%s' must be an ISO 8601 string" % name)
    elif kind == "array":
        if not isinstance(value, list):
            raise err_invalid_request("Field '%s' must be an array" % name)
    elif kind == "object":
        if not isinstance(value, dict):
            raise err_invalid_request("Field '%s' must be an object" % name)
    elif kind == "enum":
        values = spec[3]
        if not isinstance(value, str) or value not in values:
            raise err_invalid_request("Field '%s' must be one of %s" % (name, values))
    elif kind == "enum_array":
        values = spec[3]
        non_empty = spec[4] if len(spec) > 4 else False
        if not isinstance(value, list):
            raise err_invalid_request("Field '%s' must be an array" % name)
        if non_empty and len(value) == 0:
            raise err_invalid_request("Field '%s' must be a non-empty array" % name)
        for item in value:
            if not isinstance(item, str) or item not in values:
                raise err_invalid_request("Field '%s' entries must be one of %s" % (name, values))
    else:
        raise ValueError("unknown spec kind %r" % (kind,))


def get_raw_body():
    """Return the JSON request body as a dict, or {} when no body was sent.
    A present-but-malformed JSON body is a shape error (priority 1)."""
    if request.content_length in (None, 0) and not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise err_invalid_request("Request body is not valid JSON")
    if not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data


def validate_body(spec):
    """Validate the request body against an endpoint field spec.

    spec: list of tuples (field_name, kind_tuple); kind_tuple[1] is required flag.
    Undeclared extra fields are ignored. Returns the raw body dict.
    """
    body = get_raw_body()
    for name, kind in spec:
        required = kind[1]
        if name not in body:
            if required:
                raise err_invalid_request("Missing required field '%s'" % name)
            continue
        _check_value(name, body[name], kind)
    return body


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit/offset, defaults 10/0, limit min 1 max 100
# ---------------------------------------------------------------------------

def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be >= 0")
    return limit, offset


def get_filter(name):
    return request.args.get(name)


def get_int_filter(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise err_invalid_request("%s must be an integer" % name)
