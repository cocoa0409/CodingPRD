"""Authentication / authorization middleware.

Each route declares the roles it accepts; this module reads
X-User-ID / X-User-Role from the incoming Flask request.
"""
from functools import wraps
from flask import request, g

from .errors import ApiError


ALL_ROLES = {
    "PlatformAdmin",
    "AccountOwner",
    "CampaignManager",
    "FinanceOfficer",
    "CreativeReviewer",
    "ExchangeService",
    "MeasurementPartner",
    "AntiFraudService",
}

# Roles that bind to a persisted AccountUser row inside an advertiser scope.
ENTITY_BACKED_ROLES = {"AccountOwner", "CampaignManager", "FinanceOfficer"}


def require_auth(allowed_roles):
    allowed = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role:
                raise ApiError("ERR_MISSING_USER_CONTEXT")
            if role not in ALL_ROLES:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            if role not in allowed:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            g.user_id = user_id
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


def current_user_id() -> str:
    return getattr(g, "user_id", None) or ""


def current_role() -> str:
    return getattr(g, "user_role", None) or ""
