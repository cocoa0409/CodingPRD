"""Auth, RBAC, body-validation, existence, and pagination guards."""
from flask import request
from core import db, err
from domain import (
    JURISDICTIONS, SIGN_TYPES, SUBSTRATES, PERMIT_KINDS, DEFECT_KINDS,
    EQUIPMENT_CLASSES,
)

ROLES = {"ShopManager", "Designer", "Customer", "Surveyor", "PermitClerk"}


# ---------------------------------------------------------------------------
# Auth + RBAC (validation priorities 1 & 2)
# ---------------------------------------------------------------------------
def require_role(allowed):
    """Validate X-User-Role; raise ERR_UNAUTHENTICATED / ERR_FORBIDDEN."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unknown X-User-Role header")
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation")
    return role


# ---------------------------------------------------------------------------
# Body parsing
# ---------------------------------------------------------------------------
def get_body():
    if request.method in ("POST", "PATCH", "PUT"):
        data = request.get_json(silent=True)
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
        return data
    return {}


def invalid(msg):
    raise err("ERR_INVALID_REQUEST", msg)


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        invalid("Missing or invalid string field: %s" % field)
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        invalid("Missing or invalid enum field: %s" % field)
    return v


def require_number(body, field, positive=False, non_negative=False):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        invalid("Missing or invalid numeric field: %s" % field)
    if positive and not (v > 0):
        invalid("Field must be positive: %s" % field)
    if non_negative and not (v >= 0):
        invalid("Field must be non-negative: %s" % field)
    return v


def require_int(body, field, minimum=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        invalid("Missing or invalid integer field: %s" % field)
    if minimum is not None and v < minimum:
        invalid("Field below minimum: %s" % field)
    return v


def optional_bool(body, field, default):
    v = body.get(field, default)
    if v is None:
        return default
    if not isinstance(v, bool):
        invalid("Field must be a boolean: %s" % field)
    return v


def require_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        invalid("Missing or invalid boolean field: %s" % field)
    return v


def require_datetime(body, field):
    from core import parse_iso
    v = body.get(field)
    if not isinstance(v, str):
        invalid("Missing or invalid datetime field: %s" % field)
    dt = parse_iso(v)
    if dt is None:
        invalid("Unparseable datetime field: %s" % field)
    return v


def optional_datetime(body, field):
    from core import parse_iso
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str) or parse_iso(v) is None:
        invalid("Invalid datetime field: %s" % field)
    return v


# ---------------------------------------------------------------------------
# Existence (validation priority 3) — left-to-right path resolution
# ---------------------------------------------------------------------------
def get_project(project_id):
    p = db.sign_projects.get(project_id)
    if p is None:
        raise err("ERR_NOT_FOUND", "Sign project not found")
    return p


def get_child(collection, child_id, project_id):
    child = collection.get(child_id)
    if child is None or child.get("sign_project_id") != project_id:
        raise err("ERR_NOT_FOUND", "Child resource not found for this project")
    return child


# ---------------------------------------------------------------------------
# Pagination (response_envelope.pagination_defaults)
# ---------------------------------------------------------------------------
def get_pagination():
    limit = _parse_int_param("limit", 10, 1, 100)
    offset = _parse_int_param("offset", 0, 0, None)
    return limit, offset


def _parse_int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        v = int(raw)
    except (ValueError, TypeError):
        invalid("Invalid pagination parameter: %s" % name)
    if minimum is not None and v < minimum:
        invalid("Pagination %s below minimum" % name)
    if maximum is not None and v > maximum:
        invalid("Pagination %s above maximum" % name)
    return v


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
