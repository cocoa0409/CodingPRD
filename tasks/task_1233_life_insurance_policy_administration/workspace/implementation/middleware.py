"""Auth header extraction, role checking, pagination parsing, body reading.

Validation priority (PRD §2.12):
  1. header presence/well-formedness -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400)
  2. role authorization              -> ERR_INSUFFICIENT_PERMISSIONS (403)
  3. path existence, left to right   -> resource-specific 404
"""
from flask import request

import errors
from response import (
    PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX, PAGE_OFFSET_DEFAULT,
)

ROLES = {"PlatformAdmin", "Agent", "Underwriter", "PolicyIssuer", "Policyholder"}
ALL_ROLES = ["Agent", "Underwriter", "PolicyIssuer", "Policyholder", "PlatformAdmin"]


class Context:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def require_auth(allowed_roles):
    """Priority 1 + 2. Returns a Context or raises ApiError."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise errors.missing_context()
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or role not in ROLES:
        raise errors.missing_context()
    if role not in allowed_roles:
        raise errors.insufficient_permissions()
    return Context(user_id=user_id, role=role)


def parse_pagination():
    """limit/offset query params. Defaults 10/0, limit in [1,100], offset >= 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = PAGE_LIMIT_DEFAULT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise errors.invalid_request("limit must be between %d and %d"
                                         % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX))
    if raw_offset is None:
        offset = PAGE_OFFSET_DEFAULT
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer")
        if offset < PAGE_OFFSET_DEFAULT:
            raise errors.invalid_request("offset must be >= 0")
    return limit, offset


def json_body(required=False):
    """Return the request JSON body as a dict. Empty body -> {}.
    Malformed JSON or non-object -> ERR_INVALID_REQUEST."""
    data = request.get_json(silent=True)
    if data is None:
        if required:
            raise errors.invalid_request("request body must be a JSON object")
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("request body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.invalid_request("missing required field: %s" % f)


def require_int(body, field, minimum=None):
    value = body.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.invalid_request("%s must be an integer" % field)
    if minimum is not None and value < minimum:
        raise errors.invalid_request("%s must be >= %d" % (field, minimum))
    return value
