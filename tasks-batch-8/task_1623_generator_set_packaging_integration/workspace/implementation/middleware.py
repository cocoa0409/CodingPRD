"""Auth header extraction, role checking, pagination parsing, and body validation.

The PRD mandates two headers on every request:
  X-User-ID   — identity of the acting user
  X-User-Role — one of the eight declared roles

Validation priority (PRD Section 2.8):
  1. auth       — headers present, role recognized  -> ERR_UNAUTHENTICATED (401)
  2. authz      — role allowed for this endpoint     -> ERR_FORBIDDEN_ROLE (403)
  3. existence  — path ids, body FK ids              -> ERR_NOT_FOUND (404)
  4. OCC        — expected version match             -> 412
  5. state      — from-state checks                  -> 409
  6+. business rules in scaffold-defined priority order
"""

from flask import request

import errors

# The eight roles, spelled exactly as the PRD requires.
VALID_ROLES = {
    "PlatformAdmin",
    "SalesEngineer",
    "ApplicationEngineer",
    "ComplianceOfficer",
    "TestEngineer",
    "LogisticsCoordinator",
    "FieldServiceManager",
    "CustomerContact",
}


def authenticate():
    """Validate presence and correctness of auth headers.

    Returns (user_id, role) on success; raises ApiError on failure.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_roles(*allowed):
    """Authenticate, then enforce that the acting role is in *allowed*.

    Returns (user_id, role).
    """
    user_id, role = authenticate()
    if role not in allowed:
        raise errors.forbidden(
            f"Role {role} is not permitted to invoke this operation"
        )
    return user_id, role


def get_json_body():
    """Return the request JSON body as a dict; empty body becomes {}."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return body


# ---------------------------------------------------------------------------
# Pagination (PRD Section 2.3)
# ---------------------------------------------------------------------------

def parse_pagination():
    """Parse and validate limit/offset query parameters.

    Defaults: limit=10, offset=0.  Bounds: 1 <= limit <= 100, offset >= 0.
    """
    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)

    limit = 10
    offset = 0

    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise errors.invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit must be between 1 and 100")

    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0")

    return limit, offset


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------

def require_field(body, name):
    """Return body[name] or raise ERR_INVALID_REQUEST when missing/None."""
    val = body.get(name)
    if val is None:
        raise errors.invalid_request(f"Missing required field: {name}")
    return val


def require_string(body, name):
    val = require_field(body, name)
    if not isinstance(val, str):
        raise errors.invalid_request(f"{name} must be a string")
    return val


def require_int(body, name, minimum=None, maximum=None):
    val = require_field(body, name)
    # Reject booleans which are technically int subclasses in Python
    if not isinstance(val, int) or isinstance(val, bool):
        raise errors.invalid_request(f"{name} must be an integer")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"{name} must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise errors.invalid_request(f"{name} must be <= {maximum}")
    return val


def require_number(body, name, minimum=None, maximum=None, exclusive_minimum=False):
    val = require_field(body, name)
    if not isinstance(val, (int, float)) or isinstance(val, bool):
        raise errors.invalid_request(f"{name} must be a number")
    if minimum is not None:
        if exclusive_minimum:
            if val <= minimum:
                raise errors.invalid_request(f"{name} must be > {minimum}")
        else:
            if val < minimum:
                raise errors.invalid_request(f"{name} must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise errors.invalid_request(f"{name} must be <= {maximum}")
    return val


def require_enum(body, name, allowed_values):
    val = require_field(body, name)
    if val not in allowed_values:
        raise errors.invalid_request(
            f"{name} must be one of {sorted(allowed_values)}"
        )
    return val


def optional_enum(body, name, allowed_values, default):
    val = body.get(name)
    if val is None:
        return default
    if val not in allowed_values:
        raise errors.invalid_request(
            f"{name} must be one of {sorted(allowed_values)}"
        )
    return val


def optional_bool(body, name, default):
    val = body.get(name)
    if val is None:
        return default
    if not isinstance(val, bool):
        raise errors.invalid_request(f"{name} must be a boolean")
    return val


def optional_number(body, name, default, minimum=None, exclusive_minimum=False):
    val = body.get(name)
    if val is None:
        return default
    if not isinstance(val, (int, float)) or isinstance(val, bool):
        raise errors.invalid_request(f"{name} must be a number")
    if minimum is not None:
        if exclusive_minimum:
            if val <= minimum:
                raise errors.invalid_request(f"{name} must be > {minimum}")
        else:
            if val < minimum:
                raise errors.invalid_request(f"{name} must be >= {minimum}")
    return val
