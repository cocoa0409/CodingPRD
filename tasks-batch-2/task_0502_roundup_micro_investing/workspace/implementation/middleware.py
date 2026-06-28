"""Auth, RBAC, ownership, and request-parsing helpers.

PRD §2.1 — every request carries X-User-ID and X-User-Role. Four roles:
Anonymous, Investor, CustodialGuardian, PlatformAdmin.
PRD §2.9 — validation ordering: auth -> role -> ownership -> existence ->
structural -> pagination -> state -> business rules.
"""

import datetime

from flask import request

from errors import err

ROLES = {"Anonymous", "Investor", "CustodialGuardian", "PlatformAdmin"}


def get_role():
    return request.headers.get("X-User-Role")


def get_user_id():
    return request.headers.get("X-User-ID")


def require_auth(allowed_roles):
    """PRD §2.1 / §2.9 priorities 1-2.

    Priority 1: X-User-Role must be present (and X-User-ID for entity-backed
    roles). Priority 2: role must be permitted for this endpoint.
    Returns (role, user_id).
    """
    role = get_role()
    user_id = get_user_id()

    # Priority 1 — authentication headers present.
    if not role or role not in ROLES:
        raise err("ERR_MISSING_AUTH", "X-User-Role header is missing or invalid.")
    # Entity-backed roles (Investor, CustodialGuardian) also require X-User-ID.
    if role in ("Investor", "CustodialGuardian", "Anonymous", "PlatformAdmin"):
        if not user_id:
            raise err("ERR_MISSING_AUTH", "X-User-ID header is missing.")

    # Priority 2 — role permitted for the endpoint.
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s is not permitted for this endpoint." % role)

    return role, user_id


def require_owner(role, user_id, owning_account_id):
    """PRD §2.1 / §2.9 priority 3 — Investor/CustodialGuardian must own the account.

    X-User-ID must equal the resource's owning-account id. PlatformAdmin/Anonymous
    have opaque ids and are not subject to ownership checks.
    """
    if role in ("Investor", "CustodialGuardian"):
        if user_id != owning_account_id:
            raise err(
                "ERR_NOT_RESOURCE_OWNER",
                "Caller does not own the owning account of this resource.",
            )


def get_json():
    """Parse the JSON body; tolerate empty bodies on action endpoints."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def parse_pagination():
    """PRD §2.3 — limit default 10 (min 1, max 100); offset default 0 (min 0).

    Out-of-range -> ERR_INVALID_PAGINATION (priority 6).
    """
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    limit = 10
    offset = 0

    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_PAGINATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_PAGINATION", "limit must be within [1, 100].")

    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_PAGINATION", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_INVALID_PAGINATION", "offset must be >= 0.")

    return limit, offset


def parse_iso8601(value):
    """Parse an ISO 8601 UTC instant; raise ERR_INVALID_REQUEST on malformed input."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "Timestamp must be an ISO 8601 string.")
    v = value.strip()
    try:
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(v)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Malformed ISO 8601 timestamp: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)
