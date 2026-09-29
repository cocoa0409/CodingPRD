"""Auth header extraction and role checking (PRD 2.1, ladder priorities 1-2)."""

from functools import wraps

from flask import request

from errors import fail

GUEST = "Guest"
DESK = "ShoreExcursionDesk"
MANAGER = "ExcursionManager"
VETTING = "OperatorVettingOfficer"
PORT_AGENT = "PortAgent"
RISK = "RiskOfficer"
FINANCE = "FinanceController"

ALL_ROLES = (GUEST, DESK, MANAGER, VETTING, PORT_AGENT, RISK, FINANCE)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def endpoint(*allowed_roles):
    """Enforce priority 1 (identity) then priority 2 (authority)."""
    allowed = tuple(allowed_roles) if allowed_roles else ALL_ROLES

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            if user_id is None or not str(user_id).strip():
                fail("ERR_UNAUTHENTICATED", "X-User-ID header is required")
            role = request.headers.get("X-User-Role")
            if role not in allowed:
                fail("ERR_UNAUTHORIZED", "role is not authorised for this operation")
            return fn(Caller(str(user_id), role), *args, **kwargs)

        return wrapper

    return decorator
