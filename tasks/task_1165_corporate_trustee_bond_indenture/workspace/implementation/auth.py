"""Auth middleware (PRD 2.1, validation rules 1-3)."""
import functools
from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_OWNERSHIP_VIOLATION

ROLES = {"PlatformAdmin", "TrustOfficer", "TrustManager", "Issuer", "Noteholder"}
ALL_ROLES = ["PlatformAdmin", "TrustOfficer", "TrustManager", "Issuer", "Noteholder"]


def role():
    return request.headers.get("X-User-Role")


def uid():
    return request.headers.get("X-User-ID") or ""


def require_roles(*allowed):
    """Rule 1: header present and a declared role. Rule 2: role permitted here."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            r = role()
            if r is None or r not in ROLES:
                raise_err(ERR_UNAUTHENTICATED,
                          "X-User-Role header missing or not a declared role")
            if r not in allowed:
                raise_err(ERR_FORBIDDEN, "Role not permitted on this endpoint")
            return fn(*args, **kwargs)
        return wrapper
    return deco


def check_noteholder_owns(account_id):
    """Rule 3: Noteholder acts only on its own account."""
    if role() == "Noteholder" and account_id is not None and account_id != uid():
        raise_err(ERR_OWNERSHIP_VIOLATION,
                  "Noteholder may only act on its own account")


def check_issuer_owns(indenture):
    """Rule 3: Issuer acts only on indentures whose issuer_ref == X-User-ID."""
    if role() == "Issuer" and indenture is not None and indenture.get("issuer_ref") != uid():
        raise_err(ERR_OWNERSHIP_VIOLATION,
                  "Issuer does not own the target indenture")
