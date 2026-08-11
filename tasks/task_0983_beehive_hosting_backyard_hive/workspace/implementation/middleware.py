"""Auth header extraction (pipeline steps 1-2) and request body parsing."""
import json
from decimal import Decimal

from flask import request

from errors import raise_err, ERR_MISSING_OR_INVALID_CONTEXT_HEADER, ERR_FORBIDDEN_ROLE, ERR_INVALID_REQUEST

ROLES = {"Anonymous", "Host", "Beekeeper", "ApiaryManager", "PlatformOps"}
ALL_AUTHENTICATED = ("Host", "Beekeeper", "ApiaryManager", "PlatformOps")


def auth(allowed_roles):
    """Validate X-User-ID / X-User-Role headers and endpoint role authorization."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise_err(ERR_MISSING_OR_INVALID_CONTEXT_HEADER,
                  "X-User-ID and X-User-Role headers are required and the role must be declared")
    if role not in allowed_roles:
        raise_err(ERR_FORBIDDEN_ROLE, "Role %s is not permitted on this endpoint" % role)
    return uid, role


def body():
    """Parse the JSON request body preserving decimal precision. Empty body -> {}."""
    raw = request.get_data(as_text=True)
    if raw is None or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except (ValueError, TypeError):
        raise_err(ERR_INVALID_REQUEST, "Request body is not valid JSON")
    if not isinstance(parsed, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return parsed
