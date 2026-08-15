"""Auth header extraction, role checking, ownership, and body validation."""

from flask import request

from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_INVALID_REQUEST,
)

VALID_ROLES = {"SchemeAdmin", "ClientAdmin", "Auditor", "DecisionMaker", "Anonymous"}


def get_auth(allow_anonymous=False):
    """Validate X-User-ID / X-User-Role headers (priority 1).

    When allow_anonymous is True (public directory), missing headers yield an
    Anonymous caller instead of an error.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        if allow_anonymous:
            return None, "Anonymous"
        raise ApiError(
            ERR_UNAUTHENTICATED,
            "Missing or unrecognized X-User-Role / X-User-ID headers",
            401,
        )
    return user_id, role


def require_role(role, allowed):
    """Priority 2 — caller role must be listed among the endpoint's roles."""
    if role not in allowed:
        raise ApiError(
            ERR_UNAUTHORIZED, "Role not permitted for this endpoint", 403
        )


def forbid_ownership(message="Entity-backed caller does not own the target resource"):
    raise ApiError(ERR_FORBIDDEN_OWNERSHIP, message, 403)


def invalid_request(message):
    raise ApiError(ERR_INVALID_REQUEST, message, 400)


def body_preflight():
    """Validate only the JSON body's shape (dict-ness), without requiring any
    field. Safe to run before existence checks: malformed JSON is 400, but a
    well-formed body with missing fields defers field errors until after the
    existence and state checks have run (per the §2.5 priority order)."""
    data = request.get_json(silent=True)
    if data is not None and not isinstance(data, dict):
        invalid_request("Request body must be a JSON object")


def get_body(required=True):
    """Return the JSON request body as a dict, tolerating empty bodies on
    action endpoints (only when nothing is required)."""
    data = request.get_json(silent=True)
    if data is None:
        if required:
            invalid_request("Request body must be a JSON object")
        return {}
    if not isinstance(data, dict):
        invalid_request("Request body must be a JSON object")
    return data


def req_field(body, name):
    if name not in body or body[name] is None:
        invalid_request("Missing required field: %s" % name)
    return body[name]


def req_string(body, name):
    value = req_field(body, name)
    if not isinstance(value, str):
        invalid_request("Field %s must be a string" % name)
    return value


def opt_string(body, name):
    value = body.get(name)
    if value is not None and not isinstance(value, str):
        invalid_request("Field %s must be a string" % name)
    return value


def req_int(body, name):
    value = req_field(body, name)
    if isinstance(value, bool) or not isinstance(value, int):
        invalid_request("Field %s must be an integer" % name)
    return value


def req_number(body, name):
    value = req_field(body, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid_request("Field %s must be a number" % name)
    return value


def req_enum(body, name, allowed):
    value = req_field(body, name)
    if not isinstance(value, str) or value not in allowed:
        invalid_request(
            "Field %s must be one of %s" % (name, ", ".join(sorted(allowed)))
        )
    return value


def req_categories(body, name):
    """Validate a product_categories array: non-empty list of
    {category_code: non-empty string, risk_tier: STANDARD|HIGH}."""
    value = req_field(body, name)
    if not isinstance(value, list) or len(value) == 0:
        invalid_request("Field %s must be a non-empty array" % name)
    for entry in value:
        if not isinstance(entry, dict):
            invalid_request("Each %s entry must be an object" % name)
        code = entry.get("category_code")
        tier = entry.get("risk_tier")
        if not isinstance(code, str) or not code:
            invalid_request("Each %s entry requires a category_code string" % name)
        if tier not in ("STANDARD", "HIGH"):
            invalid_request(
                "Each %s entry requires risk_tier of STANDARD or HIGH" % name
            )
    return value
