from flask import g, request

import errors as E


VALID_ROLES = {"Admin", "Student", "Instructor", "Examiner", "ComplaintHandler"}


def extract_auth():
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        raise E.APIError(E.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400,
                         "X-User-ID and X-User-Role headers are required")
    if user_role not in VALID_ROLES:
        raise E.APIError(E.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400,
                         f"Unknown role: {user_role}")
    g.user_id = user_id
    g.user_role = user_role
    return user_id, user_role


def require_roles(allowed):
    if g.user_role not in allowed:
        raise E.APIError(E.ERR_INSUFFICIENT_PERMISSIONS, 403,
                         f"Role {g.user_role} not permitted")


def get_body():
    """Return the parsed JSON body as a dict, or {} if empty/missing.
    Raises ERR_INVALID_REQUEST when the body is present but malformed JSON."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "Body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, "Body must be a JSON object")
    return body


def required(body, *names):
    missing = [n for n in names if n not in body or body[n] is None or body[n] == ""]
    if missing:
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, f"Missing required fields: {', '.join(missing)}")


def required_present(body, *names):
    """Like required, but allows empty-string and falsy values; only checks presence/non-null."""
    missing = [n for n in names if n not in body or body[n] is None]
    if missing:
        raise E.APIError(E.ERR_INVALID_REQUEST, 400, f"Missing required fields: {', '.join(missing)}")
