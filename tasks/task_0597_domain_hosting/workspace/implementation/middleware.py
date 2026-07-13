"""Auth, RBAC, ownership and the account-suspension gate (PRD 2.1 / 2.8)."""

from functools import wraps

from flask import g, request

import config
import db
from errors import ApiError


def roles_required(*allowed):
    """Priority 1 (ERR_UNAUTHENTICATED) then priority 2 (ERR_FORBIDDEN_ROLE)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            user_id = request.headers.get("X-User-ID")
            if not role or role not in config.ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role != "Anonymous" and not user_id:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in allowed:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            g.role = role
            g.user_id = user_id
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def role():
    return getattr(g, "role", None)


def user_id():
    return getattr(g, "user_id", None)


def is_registrant():
    return role() == "Registrant"


def require_owner(account_id):
    """Priority 6: a Registrant may only act on resources of their own Account."""
    if is_registrant() and account_id != user_id():
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def gate_account_suspended():
    """Priority 10: a Registrant whose Account is SUSPENDED may not mutate anything."""
    if not is_registrant():
        return
    account = db.accounts.get(user_id())
    if account is not None and account["status"] == "SUSPENDED":
        raise ApiError("ERR_ACCOUNT_SUSPENDED")


def scope_to_registrant(rows, account_id_of):
    """List endpoints only ever show a Registrant their own rows."""
    if not is_registrant():
        return rows
    uid = user_id()
    return [r for r in rows if account_id_of(r) == uid]
