"""Authentication, RBAC and StoreManager scoping (PRD 2.1, ladder tiers 1-3)."""
from flask import request

from errors import fail

ROLES = (
    "StoreManager",
    "PosAssociate",
    "FraudAnalyst",
    "RiskManager",
    "LiabilityAccountant",
    "ResellerPartner",
    "PlatformAdmin",
)

ALL_ROLES = list(ROLES)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_store_manager(self):
        return self.role == "StoreManager"


def authenticate(allowed_roles):
    """Tier 1: X-User-ID present and non-empty. Tier 2: the role carried by
    X-User-Role must appear in the endpoint's declared role list."""
    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id.strip() == "":
        fail("ERR_UNAUTHENTICATED")
    role = request.headers.get("X-User-Role")
    if role is None or role.strip() == "":
        fail("ERR_UNAUTHORIZED")
    role = role.strip()
    if role not in ROLES or role not in allowed_roles:
        fail("ERR_UNAUTHORIZED")
    return Caller(user_id.strip(), role)


def scope_store(caller, effective_store_id):
    """Tier 3: a StoreManager may only act on their own store. A target whose
    effective store resolves to nothing denies the caller."""
    if not caller.is_store_manager:
        return
    if effective_store_id is None or effective_store_id != caller.user_id:
        fail("ERR_UNAUTHORIZED")


def scope_record(caller, rec, field="store_id"):
    """Scope against an already-resolved target record. A target that does not
    exist is left to the existence tier."""
    if not caller.is_store_manager or rec is None:
        return
    scope_store(caller, rec.get(field))


def scope_body_store(caller):
    """Scope a creation endpoint whose target store arrives in the body. Runs
    before body well-formedness, so the peek must never raise."""
    if not caller.is_store_manager:
        return
    body = request.get_json(silent=True)
    value = body.get("store_id") if isinstance(body, dict) else None
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_UNAUTHORIZED")
    scope_store(caller, value)
