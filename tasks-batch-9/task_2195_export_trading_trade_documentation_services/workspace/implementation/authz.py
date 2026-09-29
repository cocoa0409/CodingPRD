"""Ladder priorities 1-4 (auth/identity), 7 (buyer scope) and 9 (pagination)."""
from flask import request

from core import ApiError
from db import store

ROLES = (
    "ExportOpsCoordinator",
    "TradeComplianceOfficer",
    "DocumentaryCreditReviewer",
    "FinanceCollectionsOfficer",
    "ForeignBuyer",
    "PlatformAdmin",
)

BUYER = "ForeignBuyer"


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_buyer(self):
        return self.role == BUYER


def authenticate(allowed_roles):
    """Priorities 1-4."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or not role.strip():
        raise ApiError("ERR_MISSING_AUTH_HEADERS", 401,
                       "X-User-ID and X-User-Role are required")
    user_id = user_id.strip()
    role = role.strip()
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE", 401, "unknown role: %s" % role)
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED", 403,
                       "role %s may not call this endpoint" % role)
    if BUYER in allowed_roles and role == BUYER and user_id not in store.buyers:
        raise ApiError("ERR_BUYER_IDENTITY_NOT_FOUND", 403,
                       "X-User-ID is not a known ForeignBuyer")
    return Caller(user_id, role)


def buyer_scope(caller, order):
    """Priority 7."""
    if caller.is_buyer and order is not None and order["buyer_id"] != caller.user_id:
        raise ApiError("ERR_BUYER_SCOPE_VIOLATION", 403,
                       "resource belongs to another buyer")


# --------------------------------------------------------------------------
# pagination (priority 9)
# --------------------------------------------------------------------------
def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_PAGINATION", 422, "%s must be an integer" % name)
    value = int(text)
    if value < minimum:
        raise ApiError("ERR_INVALID_PAGINATION", 422, "%s below minimum" % name)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_PAGINATION", 422, "%s above maximum" % name)
    return value


def pagination():
    limit = _int_param("limit", 10, 1, 100)
    offset = _int_param("offset", 0, 0, None)
    return limit, offset


def apply_page(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)
