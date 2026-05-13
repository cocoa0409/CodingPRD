"""Generic helpers: pagination, OCC, version bumping, common-field assembly."""
from flask import request

from clock import iso_now
from db import new_id
from errors import APIError


# Common system fields for entities marked common_fields: true
COMMON_VERSIONED_ENTITIES = {
    "Elder", "Room", "Bed", "CareAssessment", "CarePlan",
    "Prescription", "VisitReservation", "Bill", "EpidemicConfig",
}


def new_entity(extra=None, versioned=True):
    """Create a base entity dict with common system fields."""
    now = iso_now()
    out = {"id": new_id(), "created_at": now}
    if versioned:
        out["updated_at"] = now
        out["version"] = 1
    if extra:
        out.update(extra)
    return out


def touch(entity, versioned=True):
    """Bump updated_at and version on a versioned entity."""
    entity["updated_at"] = iso_now()
    if versioned:
        entity["version"] = entity.get("version", 0) + 1


def check_occ(entity, body):
    """If `body` contains a `version` key, it must equal entity.version.

    OCC is OPTIONAL — when omitted, the check is skipped.
    """
    if body is None:
        return
    if not isinstance(body, dict):
        return
    if "version" in body and body["version"] is not None:
        if body["version"] != entity.get("version"):
            raise APIError("ERR_VERSION_CONFLICT",
                           f"Version mismatch: expected {entity.get('version')}, got {body['version']}",
                           409)


def parse_pagination():
    """Return (limit, offset) from query string, validated to scaffold defaults."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise APIError("ERR_VALIDATION", "limit must be an integer", 422)
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise APIError("ERR_VALIDATION", "offset must be an integer", 422)
    if limit < 1 or limit > 100:
        raise APIError("ERR_VALIDATION", "limit must be in [1, 100]", 422)
    if offset < 0:
        raise APIError("ERR_VALIDATION", "offset must be >= 0", 422)
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total


def require_body():
    """Return JSON body or {}. Treat invalid JSON as ERR_VALIDATION."""
    if request.method in ("GET", "DELETE"):
        return {}
    if request.content_length is None or request.content_length == 0:
        return {}
    try:
        b = request.get_json(silent=False, force=True)
    except Exception:
        raise APIError("ERR_VALIDATION", "Invalid JSON body", 422)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise APIError("ERR_VALIDATION", "Body must be a JSON object", 422)
    return b


def require_field(body, name, expected_type=None, optional=False):
    """Pull `name` from body with type check."""
    if name not in body or body[name] is None:
        if optional:
            return None
        raise APIError("ERR_VALIDATION", f"Missing required field: {name}", 422)
    val = body[name]
    if expected_type is not None and not isinstance(val, expected_type):
        # Special-case booleans: bool is an int in Python; reject when expected_type is int but value is bool
        if expected_type in (int, float) and isinstance(val, bool):
            raise APIError("ERR_VALIDATION", f"Field {name} has wrong type", 422)
        # Allow int where float expected
        if expected_type is float and isinstance(val, int) and not isinstance(val, bool):
            return float(val)
        raise APIError("ERR_VALIDATION", f"Field {name} has wrong type", 422)
    return val


def require_enum(body, name, valid_values, optional=False, default=None):
    val = body.get(name)
    if val is None:
        if optional:
            return default
        raise APIError("ERR_VALIDATION", f"Missing required field: {name}", 422)
    if val not in valid_values:
        raise APIError("ERR_VALIDATION", f"Field {name} must be one of {sorted(valid_values)}", 422)
    return val
