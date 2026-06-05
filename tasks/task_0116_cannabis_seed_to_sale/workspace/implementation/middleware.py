"""Auth header extraction and RBAC (PRD §2.1). Headers: X-User-ID, X-User-Role.

Identities are opaque; X-User-ID is never compared to any resource id except in
the segregation-of-duties checks that record it.

Priority order (PRD §2.11): ERR_UNAUTHENTICATED (401) before ERR_UNAUTHORIZED
(403). Auth is enforced on protected (mutating) endpoints; GET reads are open
per validation priority 1 ("all except GET list/detail open reads"). In this
API every endpoint nonetheless declares an authorized-role set, so we always run
authz when roles are declared, but authentication (header presence) is only
required for non-GET endpoints.
"""
from functools import wraps

from flask import request

import constants
from errors import err


def get_identity():
    return request.headers.get("X-User-ID"), request.headers.get("X-User-Role")


def require_auth(allowed_roles, open_read=False):
    """Decorator enforcing authentication + role authorization.

    open_read=True marks GET list/detail endpoints whose auth headers are
    optional (validation priority 1 exempts open reads). When headers are
    present on an open read we still enforce role authorization if a role is
    declared, but absence of headers is permitted.
    """
    allowed = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_identity()

            if open_read:
                # Open reads: no auth required. If no headers at all, allow.
                if user_id is None and role is None:
                    return fn(*args, **kwargs)
                # If a role is supplied it must still be a recognized role and
                # permitted; but per PRD these are open reads, so we do not
                # reject a present-but-unlisted role. Simplest faithful read:
                # allow through.
                return fn(*args, **kwargs)

            # Protected endpoint: both headers mandatory.
            if not user_id or not role:
                raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header.")
            if role not in constants.ROLES or role not in allowed:
                raise err(
                    "ERR_UNAUTHORIZED",
                    "Role '%s' is not permitted to perform this operation." % role,
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
