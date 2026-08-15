"""Auth header extraction, RBAC, request-shape validation, pagination.

Validation precedence bands (PRD 2.8):
  1 auth -> 2 role -> 3 ownership -> 4 request shape -> 5 existence ->
  6 OCC -> 7 state -> 8 safety/SoD -> 9 business constraints ->
  10 temporal -> 11 referential -> 12 fiscal
"""

from datetime import datetime, timezone

from flask import request

from errors import raise_err

ROLES = {
    "Provider",
    "PlanAdmin",
    "EditLibrarian",
    "EditApprover",
    "Reviewer",
    "SeniorReviewer",
    "DisputeAdjudicator",
    "PaymentIntegrityAnalyst",
}


def require_auth():
    """Band 1: headers present, role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err("ERR_UNAUTHENTICATED", "Missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def require_role(role: str, allowed):
    """Band 2: caller's role listed for the endpoint."""
    if "Any" not in allowed and role not in allowed:
        raise_err("ERR_UNAUTHORIZED_ROLE", f"Role {role} not authorized for this endpoint")


def get_body():
    """Return the JSON request body as a dict ({} when absent)."""
    if request.data is None or len(request.data) == 0:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def validate_body(body: dict, schema: dict):
    """Band 4: required fields, types, unknown fields, enums.

    schema: {field: (required, kind, enum_or_None)}
      kind in {"string", "integer", "number", "boolean", "datetime", "array"}
    Returns a dict of validated/coerced values for keys present in body
    plus defaults injected by callers. Datetimes are parsed to aware dt.
    """
    unknown = set(body.keys()) - set(schema.keys())
    if unknown:
        raise_err("ERR_INVALID_REQUEST", f"Unknown fields: {sorted(unknown)}")
    out = {}
    for name, (required, kind, enum) in schema.items():
        if name not in body or body[name] is None:
            if required:
                raise_err("ERR_INVALID_REQUEST", f"Missing required field: {name}")
            continue
        val = body[name]
        if kind == "string":
            if not isinstance(val, str):
                raise_err("ERR_INVALID_REQUEST", f"Field {name} must be a string")
        elif kind == "integer":
            if not isinstance(val, int) or isinstance(val, bool):
                raise_err("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
        elif kind == "number":
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise_err("ERR_INVALID_REQUEST", f"Field {name} must be a number")
        elif kind == "boolean":
            if not isinstance(val, bool):
                raise_err("ERR_INVALID_REQUEST", f"Field {name} must be a boolean")
        elif kind == "datetime":
            if not isinstance(val, str):
                raise_err("ERR_INVALID_REQUEST", f"Field {name} must be an ISO8601 string")
            val = parse_datetime(val)
            if val is None:
                raise_err("ERR_INVALID_REQUEST", f"Field {name} must be an ISO8601 datetime")
        elif kind == "array":
            if not isinstance(val, list):
                raise_err("ERR_INVALID_REQUEST", f"Field {name} must be an array")
        if enum is not None:
            members = val if (kind == "array" and isinstance(val, list)) else [val]
            for m in members:
                if m not in enum:
                    raise_err("ERR_INVALID_ENUM", f"Field {name} carries undeclared member: {m}")
        out[name] = val
    return out


def parse_datetime(s):
    """Parse an ISO 8601 string into an aware UTC datetime; None on failure."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    try:
        if txt.endswith("Z"):
            txt2 = txt[:-1] + "+00:00"
        else:
            txt2 = txt
        dt = datetime.fromisoformat(txt2)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def pagination_params():
    """limit/offset with PRD 2.3 defaults and bounds."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise_err("ERR_INVALID_REQUEST", "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise_err("ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        raise_err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def check_provider_owner(user_id: str, provider_id: str):
    """Band 3 ownership for Provider-role callers."""
    if provider_id != user_id:
        raise_err("ERR_NOT_RESOURCE_OWNER", "Provider may act only on own resources")
