"""Auth header extraction and RBAC enforcement (PRD 2.1, SCAFFOLD 1.4 / 1.7).

Headers (PRD 2.1):
  X-User-Role : one of CaseWorker, FinanceOfficer, Supervisor, Employer, CustodialParty
  X-User-ID   : opaque for operator roles; the acting entity id for Employer / CustodialParty
"""

from functools import wraps

from flask import request

import errors

RECOGNIZED_ROLES = {
    "CaseWorker",
    "FinanceOfficer",
    "Supervisor",
    "Employer",
    "CustodialParty",
}


class Auth:
    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id


def get_auth():
    """Validate X-User-Role; return Auth or raise ERR_UNAUTHENTICATED.

    Priority 1 (auth): X-User-Role header present and a recognized role.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in RECOGNIZED_ROLES:
        raise errors.unauthenticated()
    return Auth(role, user_id)


def require_roles(*allowed):
    """Decorator: validate auth then check the role is in the allowed set.

    Priority 1 -> ERR_UNAUTHENTICATED, Priority 2 -> ERR_FORBIDDEN.
    The decorated view receives the Auth object as its first positional arg.
    """

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            auth = get_auth()
            if auth.role not in allowed:
                raise errors.forbidden()
            return fn(auth, *args, **kwargs)

        return wrapper

    return deco
