"""Auth header extraction and role checking (PRD §2.1, scaffold validations 1-2)."""

from flask import request

import errors
from db import db

ROLES = {"LeaseAdmin", "SettlementClerk", "ComplianceOfficer", "MaintenanceCoordinator", "Driver"}

# Any role may access GET endpoints (shared read access).
ALL_ROLES = ROLES


def get_actor():
    """Extract and validate X-User-ID / X-User-Role. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.err(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and role must be a declared role",
            400,
        )
    return user_id, role


def require_roles(allowed):
    """Validate headers, then role permission. Returns (user_id, role)."""
    user_id, role = get_actor()
    if role not in allowed:
        raise errors.err(
            errors.ERR_FORBIDDEN_ROLE,
            f"Role {role} is not permitted for this endpoint",
            403,
        )
    return user_id, role


def check_ownership(user_id, owner_operator_id):
    """Driver ownership: X-User-ID must equal the resource's owner_operator_id."""
    if user_id != owner_operator_id:
        raise errors.err(
            errors.ERR_RESOURCE_NOT_OWNED,
            "Driver may act only on resources of their own lease",
            403,
        )
