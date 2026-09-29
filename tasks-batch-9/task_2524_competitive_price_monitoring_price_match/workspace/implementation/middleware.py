"""Authentication, role authorisation and store scoping (PRD 2.1, 2.9, 2.11)."""
from functools import wraps

from flask import request

from errors import err

PLATFORM_ADMIN = "PlatformAdmin"
PRICING_ANALYST = "PricingAnalyst"
PRICING_MANAGER = "PricingManager"
COMPLIANCE_OFFICER = "ComplianceOfficer"
DATA_COLLECTOR = "DataCollector"
STORE_ASSOCIATE = "StoreAssociate"
STORE_MANAGER = "StoreManager"

ALL_ROLES = (PLATFORM_ADMIN, PRICING_ANALYST, PRICING_MANAGER,
             COMPLIANCE_OFFICER, DATA_COLLECTOR, STORE_ASSOCIATE, STORE_MANAGER)

STORE_ROLES = (STORE_ASSOCIATE, STORE_MANAGER)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role are required.")
    if user_id.strip() == "" or role.strip() == "":
        raise err("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role must be non-empty.")
    if role not in ALL_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Unknown role '%s'." % role)
    return user_id, role


def endpoint(roles):
    """Wrap a view so authentication runs first and role authorisation second."""
    allowed = tuple(roles)

    def decorator(view):
        @wraps(view)
        def wrapper(**kwargs):
            user_id, role = authenticate()
            if role not in allowed:
                raise err("ERR_ROLE_FORBIDDEN",
                          "Role %s may not call this endpoint." % role)
            return view(user_id, role, **kwargs)

        return wrapper

    return decorator


def body():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return {}
    return payload


def enforce_store_scope(user_id, role, store_id):
    """PRD 2.1/2.9: store roles are confined to the store named by X-User-ID."""
    if role in STORE_ROLES and user_id != store_id:
        raise err("ERR_STORE_SCOPE_VIOLATION",
                  "Caller is scoped to store %s." % user_id)
