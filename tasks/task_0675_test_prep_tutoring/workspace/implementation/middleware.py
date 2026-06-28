"""Auth-header extraction, RBAC, and shared request helpers.

Auth headers (PRD §2.1): X-User-ID and X-User-Role. Roles: Anonymous, Student,
Instructor, Registrar.
"""
from datetime import datetime, timezone

from flask import request

from errors import err

KNOWN_ROLES = {"Anonymous", "Student", "Instructor", "Registrar"}


def get_identity():
    """Return (user_id, user_role) from headers; values may be None/blank."""
    return request.headers.get("X-User-ID"), request.headers.get("X-User-Role")


def require_auth(allowed_roles):
    """Authenticate (priority 1) then authorize role (priority 2).

    PRD §2.1: missing header or an X-User-Role not among the four known roles ->
    ERR_UNAUTHENTICATED. Well-formed headers but role not permitted ->
    ERR_UNAUTHORIZED. Returns (user_id, user_role).
    """
    user_id, role = get_identity()
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    if role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", "Role not permitted for this operation.")
    return user_id, role


def get_json_body():
    """Parse the JSON body; tolerate empty body (treated as {})."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body.")
    if data is None:
        # Empty/blank body is acceptable for no-input transition endpoints.
        if request.data.strip() == b"":
            return {}
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body.")
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3).

    limit defaults to 10, min 1, max 100; offset defaults to 0. Out-of-range or
    non-integer values are ERR_INVALID_REQUEST.
    """
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset


def parse_iso8601(value, field="timestamp"):
    """Parse an ISO 8601 instant into a timezone-aware UTC datetime."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an ISO 8601 string.")
    raw = value.strip()
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"{field} is not a valid ISO 8601 instant.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
