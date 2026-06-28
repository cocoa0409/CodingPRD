"""Auth header extraction, role checking, serialization helpers.

Auth headers (PRD §2.1 / SCAFFOLD validations priority 1-2):
  X-User-ID   — acting principal id
  X-User-Role — one of: Franchisor, ComplianceAuditor, Franchisee, FinanceClerk, System

Missing/malformed either header -> ERR_UNAUTHENTICATED (401).
Role not authorized for the endpoint -> ERR_FORBIDDEN (403).
"""
from flask import request

import errors

VALID_ROLES = {"Franchisor", "ComplianceAuditor", "Franchisee", "FinanceClerk", "System"}


def get_identity():
    """Return (user_id, role), enforcing ERR_UNAUTHENTICATED.

    A request missing or malformed in either header is rejected (PRD §2.1).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing or malformed X-User-ID header")
    if not role or role not in VALID_ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing or malformed X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """Enforce ERR_FORBIDDEN when role is not in the allowed set for the endpoint."""
    if role not in allowed:
        raise errors.err(errors.ERR_FORBIDDEN, "Role not permitted for this operation")


# --- Serialization ---
# Internal bookkeeping keys never exposed in API output.
_INTERNAL_KEYS = {"_seq"}


def serialize(record):
    """Strip internal keys; return a clean public copy."""
    return {k: v for k, v in record.items() if k not in _INTERNAL_KEYS}
