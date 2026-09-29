"""Authentication, identity resolution and the per-endpoint role allowlist.

Validation ladder rungs 1 through 3 (PRD sections 2.1 and 2.8).
"""

import functools

from flask import g, request

import constants
import db
from errors import ApiError

# Endpoints exempt from rung 2: a PracticeAdmin performs them with an opaque identifier.
IDENTITY_EXEMPT = set()


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def authenticate(roles, resolve_identity=True):
    """Decorator enforcing ladder rungs 1 (headers), 2 (identity) and 3 (allowlist)."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = _header(constants.HEADER_USER_ID)
            user_role = _header(constants.HEADER_USER_ROLE)

            # Rung 1 — both headers present and non-blank.
            if not user_id or not user_role:
                raise ApiError("ERR_UNAUTHENTICATED")

            g.user_id = user_id
            g.user_role = user_role
            g.actor = None

            # Rung 2 — identity resolution, before the endpoint role allowlist.
            role_type = constants.ROLE_TO_PROVIDER_ROLE_TYPE.get(user_role)
            if role_type is not None and resolve_identity:
                provider = db.store.get("providers", user_id)
                if provider is None:
                    raise ApiError("ERR_UNAUTHORIZED")
                if provider["role_type"] != role_type:
                    raise ApiError("ERR_UNAUTHORIZED")
                if provider["credential_status"] != "ACTIVE":
                    raise ApiError("ERR_UNAUTHORIZED")
                g.actor = provider

            # Rung 3 — role allowlist.
            if user_role not in roles:
                raise ApiError("ERR_UNAUTHORIZED")

            with db.LOCK:
                return fn(*args, **kwargs)

        return wrapper

    return decorator


ALL = list(constants.ALL_ROLES)
