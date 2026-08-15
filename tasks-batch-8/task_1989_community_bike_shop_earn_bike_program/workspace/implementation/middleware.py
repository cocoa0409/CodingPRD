"""Auth header extraction, role checking, payload schema gate.

Headers (PRD §2.1): X-User-ID and X-User-Role on every request.
Role must be exactly one of: ShopCoordinator, ProgramDirector, Volunteer,
Participant, Member. Missing headers or unknown role -> ERR_UNAUTHENTICATED (401).
Role not in the endpoint's authorized list -> ERR_FORBIDDEN (403).

The schema gate (required fields present, JSON types valid, enum members valid,
fixed numeric ranges) runs with the envelope/auth checks, BEFORE any resource
lookup (validation priority 3, ERR_VALIDATION 400).
"""

from flask import request

from errors import ApiError

ROLES = {"ShopCoordinator", "ProgramDirector", "Volunteer", "Participant", "Member"}


def get_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or unknown X-User-ID / X-User-Role headers")
    return user_id, role


def require_roles(*roles):
    """Authenticate and require the caller's role to be in `roles`."""
    user_id, role = get_auth()
    if role not in roles:
        raise ApiError("ERR_FORBIDDEN", f"Role {role} is not authorized for this endpoint")
    return user_id, role


def get_body():
    """Return the JSON request body as a dict (empty body -> {}). Non-object -> 400."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_VALIDATION", "Request body must be valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object")
    return body


def _type_ok(value, spec):
    if spec == "string":
        return isinstance(value, str)
    if spec == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if spec == "number":
        return (isinstance(value, (int, float)) and not isinstance(value, bool))
    if spec == "boolean":
        return isinstance(value, bool)
    if spec == "object":
        return isinstance(value, dict)
    if spec == "array":
        return isinstance(value, list)
    return True


def validate_payload(body, spec):
    """Schema gate. `spec` is a dict of field -> descriptor:
    {"type": "string"|"integer"|"number"|"boolean"|"object"|"array",
     "required": bool, "enum": [...], "min_int": n, "max_int": n}
    Raises ERR_VALIDATION (400) on the first violation.
    """
    for field, desc in spec.items():
        present = field in body and body[field] is not None
        if desc.get("required") and not present:
            raise ApiError("ERR_VALIDATION", f"Missing required field: {field}")
        if not present:
            continue
        value = body[field]
        if not _type_ok(value, desc.get("type")):
            raise ApiError("ERR_VALIDATION", f"Field {field} has an invalid type")
        if "enum" in desc and value not in desc["enum"]:
            raise ApiError("ERR_VALIDATION", f"Field {field} is not a recognized enum member")
        if "min_int" in desc and isinstance(value, int) and value < desc["min_int"]:
            raise ApiError("ERR_VALIDATION", f"Field {field} is below its minimum")
        if "max_int" in desc and isinstance(value, int) and value > desc["max_int"]:
            raise ApiError("ERR_VALIDATION", f"Field {field} exceeds its maximum")
