"""Auth header extraction and RBAC enforcement (PRD §2.1, §2.10; scaffold §1.4/§1.7).

Auth headers (PRD §2.1):
  X-User-ID   — acting user id
  X-User-Role — one of {Anonymous, Guardian, ProgramDirector, BillingAdmin}

Validation ordering (PRD §2.10): ERR_UNAUTHENTICATED (auth) precedes
ERR_FORBIDDEN_ROLE (role authorization), which precedes ERR_NOT_FOUND.
"""
from __future__ import annotations

from flask import request

from errors import APIError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

ROLE_ANONYMOUS = "Anonymous"
ROLE_GUARDIAN = "Guardian"
ROLE_DIRECTOR = "ProgramDirector"
ROLE_BILLING = "BillingAdmin"

VALID_ROLES = {ROLE_ANONYMOUS, ROLE_GUARDIAN, ROLE_DIRECTOR, ROLE_BILLING}


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Authenticate the request headers.

    Both X-User-ID and X-User-Role must be present and well-formed; the role must
    be one of the recognized values. Missing/malformed -> ERR_UNAUTHENTICATED (401).
    Anonymous is a recognized role here (it is the role used to register guardians);
    role-permission is decided separately by require_roles().
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if role is None or role == "" or role not in VALID_ROLES:
        raise APIError(ERR_UNAUTHENTICATED, 401, "Missing or malformed X-User-Role")
    if user_id is None or user_id == "":
        # Anonymous identity is opaque, but the header still must be present/well-formed.
        raise APIError(ERR_UNAUTHENTICATED, 401, "Missing or malformed X-User-ID")
    return Caller(user_id, role)


def require_roles(*allowed_roles: str) -> Caller:
    """Authenticate, then ensure the caller's role is permitted for the operation.

    Not permitted -> ERR_FORBIDDEN_ROLE (403). Order matches PRD §2.10:
    authentication first, then role authorization.
    """
    caller = get_caller()
    if caller.role not in allowed_roles:
        raise APIError(ERR_FORBIDDEN_ROLE, 403, f"Role {caller.role} may not perform this operation")
    return caller
