"""Authentication & RBAC helpers.

Per PRD §2.1 every request must carry both X-User-ID and X-User-Role and the
role must belong to the closed set {EscrowOfficer, TitleOfficer,
DisbursementApprover, Buyer, Seller}.
"""
from __future__ import annotations

from typing import Iterable, Tuple

from flask import request

from app.errors import ApiError


ROLES_ALL = {"EscrowOfficer", "TitleOfficer", "DisbursementApprover", "Buyer", "Seller"}


def require_auth() -> Tuple[str, str]:
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role or user_role not in ROLES_ALL:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid auth headers.")
    return user_id, user_role


def require_role(allowed: Iterable[str]) -> Tuple[str, str]:
    user_id, user_role = require_auth()
    if user_role not in set(allowed):
        raise ApiError("ERR_FORBIDDEN_ROLE", f"Role {user_role} is not permitted for this endpoint.")
    return user_id, user_role
