"""Auth header extraction and role enforcement (validations §1.4 priorities 1-2,
PRD §2.1 and §3.8).

Priority 1 (ERR_UNAUTHENTICATED): X-User-ID and X-User-Role present and
well-formed. "Well-formed" for the role means it is one of the four recognized
role strings; for the id it means a non-empty string.

Priority 2 (ERR_UNAUTHORIZED): the named role is permitted for the operation.

Ownership (priority 4, ERR_NOT_RESOURCE_OWNER) is enforced per-endpoint, not
here, because it depends on the targeted resource's foreign keys.
"""

from functools import wraps
from flask import request

from errors import raise_api


VALID_ROLES = {"Applicant", "Attorney", "Examiner", "TTABClerk"}


def _extract_auth():
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    if role is None or not isinstance(role, str) or role.strip() == "":
        raise_api("ERR_UNAUTHENTICATED", "X-User-Role missing")
    if user_id is None or not isinstance(user_id, str) or user_id.strip() == "":
        raise_api("ERR_UNAUTHENTICATED", "X-User-ID missing")

    role = role.strip()
    user_id = user_id.strip()

    # A malformed (unrecognized) role value is an authentication failure.
    if role not in VALID_ROLES:
        raise_api("ERR_UNAUTHENTICATED", "X-User-Role is not a recognized role")

    return user_id, role


def require_roles(*allowed_roles):
    """Decorator: validate auth headers (priority 1), then role gate (priority 2)."""
    allowed_set = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = _extract_auth()
            if role not in allowed_set:
                raise_api(
                    "ERR_UNAUTHORIZED",
                    f"Role {role} is not permitted on this endpoint",
                )
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator
