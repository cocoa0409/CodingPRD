"""Auth middleware, body validators, datetime parsing, and pagination."""
import functools
import re
from datetime import datetime, timezone

from flask import g, request

from errors import invalid_request, unauthenticated, unauthorized

ROLES = {
    "SustainabilityManager",
    "SustainabilityAnalyst",
    "SiteDataSteward",
    "DisclosureLead",
    "AssuranceProvider",
    "SupplierContact",
}

MANAGER = "SustainabilityManager"
ANALYST = "SustainabilityAnalyst"
STEWARD = "SiteDataSteward"
DISCLOSURE_LEAD = "DisclosureLead"
ASSURANCE = "AssuranceProvider"
SUPPLIER = "SupplierContact"

# Standard read set for business resources (PRD §4) — no SupplierContact.
READ_ROLES = (MANAGER, ANALYST, STEWARD, DISCLOSURE_LEAD, ASSURANCE)
# Engagement reads — no SiteDataSteward / DisclosureLead.
ENGAGEMENT_READ_ROLES = (MANAGER, ANALYST, SUPPLIER, ASSURANCE)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def require_roles(*roles):
    """Priority 1 (authentication) then priority 2 (endpoint role membership)."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise unauthenticated()
            if role not in roles:
                raise unauthorized(f"Role {role} is not permitted for this endpoint")
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


def require_target_role(body, mapping):
    """Priority 2 (authorization for the specific transition target).

    ``mapping`` maps a recognized to_state/decision to the single permitted
    role. Unknown or missing targets are skipped here; request-shape
    validation (priority 4) rejects them later.
    """
    target = body.get("to_state")
    if isinstance(target, str) and target in mapping:
        need = mapping[target]
        if g.user_role != need:
            raise unauthorized(
                f"Transition to {target} is permitted to role {need} only"
            )


def get_body():
    """Parse the JSON request body; a missing/malformed/non-object body is {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def v_str(body, name, required=True):
    v = body.get(name)
    if v is None:
        if required:
            raise invalid_request(f"Missing required field: {name}")
        return None
    if not isinstance(v, str) or v == "":
        raise invalid_request(f"Field {name} must be a non-empty string")
    return v


def v_int(body, name, required=True):
    v = body.get(name)
    if v is None:
        if required:
            raise invalid_request(f"Missing required field: {name}")
        return None
    if not _is_int(v):
        raise invalid_request(f"Field {name} must be an integer")
    return v


def v_num(body, name, required=True, gt=None, gte=None, lt=None):
    v = body.get(name)
    if v is None:
        if required:
            raise invalid_request(f"Missing required field: {name}")
        return None
    if not _is_num(v):
        raise invalid_request(f"Field {name} must be a number")
    if gt is not None and not v > gt:
        raise invalid_request(f"Field {name} must be > {gt}")
    if gte is not None and not v >= gte:
        raise invalid_request(f"Field {name} must be >= {gte}")
    if lt is not None and not v < lt:
        raise invalid_request(f"Field {name} must be < {lt}")
    return v


def v_enum(body, name, values, required=True):
    v = body.get(name)
    if v is None:
        if required:
            raise invalid_request(f"Missing required field: {name}")
        return None
    if not isinstance(v, str) or v not in values:
        raise invalid_request(f"Field {name} must be one of {sorted(values)}")
    return v


def parse_iso(value):
    """Parse an ISO-8601 datetime string to an aware UTC datetime, or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def v_datetime(body, name, required=True):
    """Validate an ISO-8601 datetime field; returns (raw_string, parsed_dt)."""
    raw = body.get(name)
    if raw is None:
        if required:
            raise invalid_request(f"Missing required field: {name}")
        return None, None
    parsed = parse_iso(raw)
    if parsed is None:
        raise invalid_request(f"Field {name} must be an ISO 8601 datetime")
    return raw, parsed


def v_version(body, name):
    """OCC field (non-optional per PRD 2.8).

    Accepts an int, an integer-valued float, or a decimal string (test
    harness capture substitution may stringify the value).
    """
    v = body.get(name)
    if v is None:
        raise invalid_request(f"Missing required field: {name}")
    if _is_int(v):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        return int(v.strip())
    raise invalid_request(f"Field {name} must be an integer")


def parse_pagination():
    """limit: default 10, min 1, max 100; offset: default 0, min 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("Query parameter limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("Query parameter limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("Query parameter offset must be an integer")
        if offset < 0:
            raise invalid_request("Query parameter offset must be >= 0")
    return limit, offset
