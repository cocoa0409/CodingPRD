"""Authentication (ladder rank 1) and authorisation (rank 2), plus lazy body
decoding so that path resolution (rank 3) always precedes schema checks (rank 6).
"""
import functools
import json
from decimal import Decimal

from flask import g, request

import config
from errors import fail
from validation import Body


def endpoint(roles):
    """Wrap a view: verify the two headers and the role list before anything else."""
    allowed = tuple(roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not str(user_id).strip() or not role:
                fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
            if role not in config.ROLES:
                fail("ERR_UNAUTHENTICATED", "Unknown role '%s'." % role)
            g.user_id = user_id
            g.role = role
            if role not in allowed:
                fail("ERR_FORBIDDEN_ROLE", "Role '%s' may not perform this operation." % role)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def body(allow_version_fields=()):
    """Decode the request body, keeping decimal literals exact."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        payload = {}
    else:
        try:
            payload = json.loads(raw, parse_float=Decimal)
        except ValueError:
            fail("ERR_INVALID_REQUEST", "Request body must be valid JSON.")
    return Body(payload, allow_version_fields=allow_version_fields)
