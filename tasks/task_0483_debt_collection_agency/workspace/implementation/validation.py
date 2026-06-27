"""Request body parsing and field validation helpers.

Evaluation order (PRD 2.10): auth -> RBAC -> existence -> body well-formedness
(ERR_INVALID_REQUEST) -> state -> domain guardrails. These helpers cover the
body-well-formedness layer; callers invoke them only after existence checks.
"""
from flask import request

from errors import ApiError, ERR_INVALID_REQUEST


def get_body():
    """Return the JSON body as a dict; {} when empty. Malformed JSON -> 400."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError(*ERR_INVALID_REQUEST, message="Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(*ERR_INVALID_REQUEST, message="Body must be a JSON object")
    return body


def invalid(msg):
    raise ApiError(*ERR_INVALID_REQUEST, message=msg)


def require_str(body, field):
    val = body.get(field)
    if not isinstance(val, str) or not val.strip():
        invalid("Field '%s' is required and must be a non-empty string" % field)
    return val


def optional_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str):
        invalid("Field '%s' must be a string" % field)
    return val


def require_enum(body, field, choices):
    val = body.get(field)
    if not isinstance(val, str) or val not in choices:
        invalid("Field '%s' must be one of %s" % (field, sorted(choices)))
    return val


def optional_enum(body, field, choices, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in choices:
        invalid("Field '%s' must be one of %s" % (field, sorted(choices)))
    return val


def require_int(body, field):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        invalid("Field '%s' is required and must be an integer" % field)
    return val


def optional_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        invalid("Field '%s' must be an integer" % field)
    return val


def require_positive_int(body, field):
    val = require_int(body, field)
    if val <= 0:
        invalid("Field '%s' must be greater than zero" % field)
    return val
