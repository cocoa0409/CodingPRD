"""Auth-context extraction and request-body validation helpers."""
from flask import request
import errors


ROLES = {"LeadEstimator", "ChiefEstimator", "PrequalReviewer", "Subcontractor", "Anonymous"}


def get_context():
    """Return (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.err_missing_context()
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise errors.err_forbidden_role()


def get_json_body():
    """Return parsed JSON body ({} when no body). Raise ERR_INVALID_REQUEST on bad JSON."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=False, silent=False)
    except Exception:
        raise errors.err_invalid_request("Request body must be valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.err_invalid_request("Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.err_invalid_request(f"Missing required field: {f}")


def reject_unexpected(body, allowed):
    """Reject any field the endpoint does not accept (incl. computed/read-only)."""
    for k in body:
        if k not in allowed:
            raise errors.err_invalid_request(f"Unexpected or read-only field: {k}")


def require_int(body, field, minimum=None, strict_minimum=None):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise errors.err_invalid_request(f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise errors.err_invalid_request(f"Field {field} must be >= {minimum}")
    if strict_minimum is not None and v <= strict_minimum:
        raise errors.err_invalid_request(f"Field {field} must be > {strict_minimum}")
    return v


def require_number(body, field, strict_minimum=None, minimum=None, maximum=None):
    v = body.get(field)
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise errors.err_invalid_request(f"Field {field} must be a number")
    if strict_minimum is not None and v <= strict_minimum:
        raise errors.err_invalid_request(f"Field {field} must be > {strict_minimum}")
    if minimum is not None and v < minimum:
        raise errors.err_invalid_request(f"Field {field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise errors.err_invalid_request(f"Field {field} must be <= {maximum}")
    return v


def require_string(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise errors.err_invalid_request(f"Field {field} must be a string")
    return v


def require_enum(body, field, members):
    v = body.get(field)
    if v not in members:
        raise errors.err_invalid_request(f"Field {field} must be one of {sorted(members)}")
    return v


def parse_limit_offset(args):
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.err_invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.err_invalid_request("offset must be an integer")
        if offset < 0:
            raise errors.err_invalid_request("offset must be >= 0")
    return limit, offset
