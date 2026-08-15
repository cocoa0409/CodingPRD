"""Auth middleware: X-User-ID / X-User-Role header validation and RBAC (PRD 2.1)."""
from functools import wraps

from flask import g, request

import db
import errors

ROLES = {"StadiumAdmin", "PremiumSalesRep", "FinanceController", "EventServicesManager", "AccountHolder"}
ALL_ROLES = ["StadiumAdmin", "PremiumSalesRep", "FinanceController", "EventServicesManager", "AccountHolder"]


def authenticate():
    """Gate 1: header presence and validity."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise errors.err_missing_user_context()
    g.user_id = uid
    g.role = role
    return uid, role


def require_roles(*roles):
    """Gates 1-2: header validity, then endpoint role membership."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = authenticate()
            if role not in roles:
                raise errors.err_forbidden()
            return fn(*args, **kwargs)
        return wrapper
    return deco


def is_holder():
    return g.role == "AccountHolder"


def check_scope(account_id):
    """Gate 4: AccountHolder must address only its own account's resources."""
    if g.role == "AccountHolder" and g.user_id != account_id:
        raise errors.err_scope()


def get_or_404(coll, eid):
    ent = db.get(coll, eid)
    if ent is None:
        raise errors.err_not_found(f"{coll} resource {eid} not found")
    return ent


def resolve_fk(coll, eid):
    """Gate 5: body-supplied foreign keys must resolve."""
    if not isinstance(eid, str):
        raise errors.err_invalid_request("foreign key id must be a string")
    ent = db.get(coll, eid)
    if ent is None:
        raise errors.err_not_found(f"referenced {coll} resource {eid} not found")
    return ent
