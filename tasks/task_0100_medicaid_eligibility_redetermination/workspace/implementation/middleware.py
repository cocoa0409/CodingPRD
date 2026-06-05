"""Auth header extraction, RBAC, pagination, and body validation helpers.

Auth (PRD §2.1): two mandatory headers X-User-ID and X-User-Role.
Roles are exactly Applicant, CaseWorker, HearingOfficer. Missing either header
or an undeclared role -> ERR_UNAUTHENTICATED (401). Authenticated but role not
permitted for the endpoint -> ERR_FORBIDDEN (403).
"""
from __future__ import annotations

from typing import Iterable, Optional
from flask import request, g

from errors import (
    APIError,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
)

DECLARED_ROLES = {"Applicant", "CaseWorker", "HearingOfficer"}

# Pagination defaults (scaffold §1.0 pagination_defaults / PRD §2.3).
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def authenticate(allowed_roles: Iterable[str]):
    """Priority 1 (auth) then priority 2 (RBAC).

    Sets g.user_role and g.user_id on success.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    # Priority 1: both headers present and role is a declared role.
    if not role or not user_id or role not in DECLARED_ROLES:
        raise APIError(ERR_UNAUTHENTICATED, 401, "Missing or invalid X-User-Role / X-User-ID headers")
    g.user_role = role
    g.user_id = user_id
    # Priority 2: role permitted for this endpoint.
    if role not in set(allowed_roles):
        raise APIError(ERR_FORBIDDEN, 403, "Acting role not permitted for this endpoint")


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)


# --- Pagination -------------------------------------------------------------

def parse_pagination() -> tuple[int, int]:
    """Parse limit/offset query params with defaults and bounds.

    limit defaults 10, min 1, max 100. offset defaults 0, min 0. Malformed or
    out-of-range values -> ERR_INVALID_REQUEST (422).
    """
    limit = _parse_int_param("limit", LIMIT_DEFAULT)
    offset = _parse_int_param("offset", OFFSET_DEFAULT)
    if limit < LIMIT_MIN or limit > LIMIT_MAX:
        raise APIError(ERR_INVALID_REQUEST, 422, "limit out of range")
    if offset < 0:
        raise APIError(ERR_INVALID_REQUEST, 422, "offset must be non-negative")
    return limit, offset


def _parse_int_param(name: str, default: int) -> int:
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise APIError(ERR_INVALID_REQUEST, 422, f"{name} must be an integer")


def paginate(items: list, limit: int, offset: int) -> tuple[list, int]:
    total = len(items)
    return items[offset:offset + limit], total


# --- Body parsing -----------------------------------------------------------

def get_json_body() -> dict:
    """Return the request JSON body as a dict (empty dict when absent).

    A non-object JSON body (e.g. a list or scalar) is malformed.
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 422, "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise APIError(ERR_INVALID_REQUEST, 422, "Request body must be a JSON object")
    return body
