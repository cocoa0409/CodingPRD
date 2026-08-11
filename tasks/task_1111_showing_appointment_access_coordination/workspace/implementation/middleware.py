"""Auth header extraction, role checking, request-shape validation helpers.

Validation pipeline order per PRD §2.7:
  1. Authentication (ERR_UNAUTHENTICATED)
  2. Request shape (ERR_INVALID_REQUEST / ERR_RATING_OUT_OF_RANGE)
  3. Role authorization (ERR_FORBIDDEN_ROLE)
  4. Existence (per-resource 404s, left-to-right along path, then body FKs)
  5. Ownership (ERR_NOT_RESOURCE_OWNER)
  6. OCC (stale version)
  7+ business rules
"""

from flask import request

import clock
import errors


ROLES = {"Anonymous", "PlatformAdmin", "Seller", "ListingAgent", "BuyerAgent"}
ENTITY_BACKED = {"Seller", "ListingAgent", "BuyerAgent"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Stage 1: headers present and role recognized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED,
                         "Missing or invalid X-User-ID / X-User-Role headers.", 401)
    return Caller(user_id, role)


def require_roles(caller, roles):
    """Stage 3: role authorization."""
    if caller.role not in roles:
        raise errors.err(errors.ERR_FORBIDDEN_ROLE,
                         f"Role {caller.role} is not authorized for this endpoint.", 403)


def get_json_body(required=True):
    """Return the JSON request body as a dict, or raise ERR_INVALID_REQUEST.

    For POST endpoints with no documented inputs, an absent/empty body is allowed
    and yields {}.
    """
    if not request.data:
        if required:
            raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be JSON.", 400)
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be valid JSON.", 400)
    if not isinstance(body, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object.", 400)
    return body


def validate_fields(body, spec, allow_empty_body=False):
    """Validate body shape against spec: {field: (type_kind, required)}.

    type_kind one of: 'string', 'integer', 'boolean', 'number', 'datetime',
    ('enum', [values]). Unknown fields are rejected.
    """
    if not body and allow_empty_body:
        body = {}
    unknown = set(body.keys()) - set(spec.keys())
    if unknown:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         f"Unknown field(s): {', '.join(sorted(unknown))}.", 400)
    out = {}
    for name, rule in spec.items():
        kind, required = rule[0], rule[1]
        present = name in body and body[name] is not None
        if not present:
            if name in body and body[name] is None and required:
                raise errors.err(errors.ERR_INVALID_REQUEST,
                                 f"Field '{name}' is required.", 400)
            if required:
                raise errors.err(errors.ERR_INVALID_REQUEST,
                                 f"Field '{name}' is required.", 400)
            continue
        val = body[name]
        if kind == "string":
            if not isinstance(val, str):
                raise errors.err(errors.ERR_INVALID_REQUEST,
                                 f"Field '{name}' must be a string.", 400)
        elif kind == "integer":
            if isinstance(val, bool) or not isinstance(val, int):
                raise errors.err(errors.ERR_INVALID_REQUEST,
                                 f"Field '{name}' must be an integer.", 400)
        elif kind == "boolean":
            if not isinstance(val, bool):
                raise errors.err(errors.ERR_INVALID_REQUEST,
                                 f"Field '{name}' must be a boolean.", 400)
        elif kind == "number":
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise errors.err(errors.ERR_INVALID_REQUEST,
                                 f"Field '{name}' must be a number.", 400)
        elif kind == "datetime":
            parsed = clock.parse_iso(val)
            if parsed is None:
                raise errors.err(errors.ERR_INVALID_REQUEST,
                                 f"Field '{name}' must be an ISO 8601 timestamp.", 400)
            val = parsed
        elif isinstance(kind, tuple) and kind[0] == "enum":
            if not isinstance(val, str) or val not in kind[1]:
                raise errors.err(errors.ERR_INVALID_REQUEST,
                                 f"Field '{name}' must be one of {kind[1]}.", 400)
        out[name] = val
    return out


def parse_pagination():
    """Parse limit/offset query params with defaults limit=10 (min 1, max 100), offset=0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_INVALID_REQUEST,
                             "Query parameter 'limit' must be an integer.", 400)
        if limit < 1 or limit > 100:
            raise errors.err(errors.ERR_INVALID_REQUEST,
                             "Query parameter 'limit' must be between 1 and 100.", 400)
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.err(errors.ERR_INVALID_REQUEST,
                             "Query parameter 'offset' must be an integer.", 400)
        if offset < 0:
            raise errors.err(errors.ERR_INVALID_REQUEST,
                             "Query parameter 'offset' must be >= 0.", 400)
    return limit, offset


def paginate(items, limit, offset):
    """Slice a pre-sorted list; returns (page, total_count)."""
    total = len(items)
    return items[offset:offset + limit], total
