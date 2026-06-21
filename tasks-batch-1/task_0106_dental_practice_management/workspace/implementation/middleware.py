"""Auth header extraction and role checking (PRD §2.1, §2.8).

Every request authenticates through two mandatory headers:
  X-User-ID   — the acting user
  X-User-Role — the capacity (one of the four recognized roles)

Missing header or unknown role -> ERR_UNAUTHENTICATED (401).
Known role not permitted for the operation -> ERR_FORBIDDEN (403).
"""
from __future__ import annotations

from typing import Iterable

from flask import g, request

from errors import APIError, ERR_FORBIDDEN, ERR_UNAUTHENTICATED

ROLE_FRONT_DESK = "FrontDesk"
ROLE_CLINICIAN = "Clinician"
ROLE_BILLING = "BillingSpecialist"
ROLE_PATIENT = "Patient"

KNOWN_ROLES = {ROLE_FRONT_DESK, ROLE_CLINICIAN, ROLE_BILLING, ROLE_PATIENT}


def authenticate() -> None:
    """Validate the two auth headers; populate g.user_id / g.user_role.

    Auth (ERR_UNAUTHENTICATED) is the very first check (PRD §2.8).
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id:
        raise APIError(ERR_UNAUTHENTICATED, 401, "Missing X-User-ID or X-User-Role header")
    if role not in KNOWN_ROLES:
        raise APIError(ERR_UNAUTHENTICATED, 401, "Unknown X-User-Role")
    g.user_id = user_id
    g.user_role = role


def require_roles(allowed: Iterable[str]) -> None:
    """Authorization (ERR_FORBIDDEN) — runs immediately after authenticate()."""
    allowed_set = set(allowed)
    if g.user_role not in allowed_set:
        raise APIError(ERR_FORBIDDEN, 403, "Role not permitted for this operation")


def current_role() -> str:
    return getattr(g, "user_role", None)


def current_user_id() -> str:
    return getattr(g, "user_id", None)
