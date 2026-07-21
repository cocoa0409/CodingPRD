"""Authentication, authorization, and Designer ownership (PRD §2.1)."""
from functools import wraps

from flask import request, g

from errors import err
from store import db

ROLES = {"ShowroomAssociate", "FulfillmentCoordinator", "Designer", "StoreManager"}


def _authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    g.user_id = user_id
    g.role = role
    return user_id, role


def require(*allowed_roles):
    """Decorator: authenticate, then authorize against the allowed role set.

    StoreManager is a hierarchical-override operator authorized everywhere.
    """
    allowed = set(allowed_roles) | {"StoreManager"}

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = _authenticate()
            if role not in allowed:
                raise err("ERR_UNAUTHORIZED", "Role not permitted for this endpoint")
            return fn(*args, **kwargs)

        return wrapper

    return deco


def check_designer_ownership(trade_account_id):
    """Designer ownership-and-active guard (ERR_ACCOUNT_FORBIDDEN, last business check).

    Only applies when the acting role is Designer. The Designer's X-User-ID must
    equal the resource's trade_account_id and that account must be ACTIVE.
    """
    if g.get("role") != "Designer":
        return
    if trade_account_id is None or g.get("user_id") != trade_account_id:
        raise err("ERR_ACCOUNT_FORBIDDEN", "Designer does not own this resource")
    acct = db.trade_accounts.get(trade_account_id)
    if acct is None or acct.get("status") != "ACTIVE":
        raise err("ERR_ACCOUNT_FORBIDDEN", "Trade account is not ACTIVE")
