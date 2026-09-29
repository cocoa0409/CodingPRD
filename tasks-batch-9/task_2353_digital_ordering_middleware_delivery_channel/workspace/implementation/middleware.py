"""Identity, RBAC and scope enforcement (PRD 2.1, ranks 1/2/5/6 of PRD 2.8)."""
from functools import wraps

from flask import g, request

import errors
from errors import fail

PLATFORM_ADMIN = "PlatformAdmin"
STORE_OPERATOR = "StoreOperator"
CHANNEL_PARTNER = "ChannelPartner"
COURIER_AGENT = "CourierNetworkAgent"
SETTLEMENT_ANALYST = "SettlementAnalyst"

ROLES = (
    PLATFORM_ADMIN,
    STORE_OPERATOR,
    CHANNEL_PARTNER,
    COURIER_AGENT,
    SETTLEMENT_ANALYST,
)

_SCOPE_HEADER = {
    STORE_OPERATOR: "X-Store-ID",
    CHANNEL_PARTNER: "X-Channel-ID",
    COURIER_AGENT: "X-Courier-Network-ID",
}


class Identity(object):
    def __init__(self, role, user_id, headers):
        self.role = role
        self.user_id = user_id
        header = _SCOPE_HEADER.get(role)
        scope = None
        if header:
            scope = headers.get(header)
            if scope is not None and not scope.strip():
                scope = None
            if scope is None:
                # An entity-backed role that omits its scope header falls back
                # to interpreting X-User-ID as the acting entity's id.
                scope = user_id
        self.scope_id = scope


def identity():
    return g.identity


def endpoint(*roles):
    """Rank 1 (401) and rank 2 (403) of the rejection ladder."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role") or request.headers.get("X-Role")
            user_id = request.headers.get("X-User-ID")
            if role is not None and not role.strip():
                role = None
            if user_id is not None and not user_id.strip():
                user_id = None
            if role is None or user_id is None or role not in ROLES:
                fail(errors.ERR_UNAUTHENTICATED)
            if role not in roles:
                fail(errors.ERR_UNAUTHORIZED)
            g.identity = Identity(role, user_id, request.headers)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# --- rank 5: ERR_FORBIDDEN_SCOPE -------------------------------------------

def require_store_scope(store_id):
    ident = identity()
    if ident.role == STORE_OPERATOR and ident.scope_id != store_id:
        fail(errors.ERR_FORBIDDEN_SCOPE)


def require_channel_scope(channel_id):
    ident = identity()
    if ident.role == CHANNEL_PARTNER and ident.scope_id != channel_id:
        fail(errors.ERR_FORBIDDEN_SCOPE)


def require_network_scope(network_id):
    ident = identity()
    if ident.role == COURIER_AGENT and ident.scope_id != network_id:
        fail(errors.ERR_FORBIDDEN_SCOPE)


def require_order_scope(order):
    require_store_scope(order["store_id"])
    require_channel_scope(order["channel_id"])
