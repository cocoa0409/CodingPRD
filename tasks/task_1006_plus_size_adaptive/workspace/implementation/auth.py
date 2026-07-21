"""Auth extraction, structural validation, and pagination helpers."""
from flask import request

from envelope import ApiError
from store import db, ROLES, parse_dt


# ---------------------------------------------------------------------------
# Structural (400) validation
# ---------------------------------------------------------------------------
def get_body():
    """Parse the JSON body; malformed -> ERR_VALIDATION (400). Missing body -> {}."""
    if request.method in ("GET", "DELETE"):
        return {}
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "Body must be a JSON object")
    return data


def _type_ok(value, typ):
    if typ == "string":
        return isinstance(value, str)
    if typ == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if typ == "number":
        return (isinstance(value, (int, float)) and not isinstance(value, bool))
    if typ == "boolean":
        return isinstance(value, bool)
    if typ == "array":
        return isinstance(value, list)
    if typ == "datetime":
        if not isinstance(value, str):
            return False
        try:
            parse_dt(value)
            return True
        except Exception:
            return False
    return True


def require(body, name, typ, enum=None):
    """Required field: must be present, correct type, valid enum member."""
    if name not in body or body[name] is None:
        raise ApiError("ERR_VALIDATION", 400, f"Missing required field '{name}'")
    val = body[name]
    if not _type_ok(val, typ):
        raise ApiError("ERR_VALIDATION", 400, f"Field '{name}' has wrong type")
    if enum is not None and val not in enum:
        raise ApiError("ERR_VALIDATION", 400, f"Field '{name}' has invalid value")
    return val


def optional(body, name, typ, default=None, enum=None):
    """Optional field: if present must be correct type / enum member."""
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not _type_ok(val, typ):
        raise ApiError("ERR_VALIDATION", 400, f"Field '{name}' has wrong type")
    if enum is not None and val not in enum:
        raise ApiError("ERR_VALIDATION", 400, f"Field '{name}' has invalid value")
    return val


def require_str_array(body, name, required=True, default=None):
    """A field that must be a list of strings."""
    if name not in body or body[name] is None:
        if required:
            raise ApiError("ERR_VALIDATION", 400, f"Missing required field '{name}'")
        return list(default) if default is not None else []
    val = body[name]
    if not isinstance(val, list) or any(not isinstance(x, str) for x in val):
        raise ApiError("ERR_VALIDATION", 400, f"Field '{name}' must be an array of strings")
    return val


# ---------------------------------------------------------------------------
# Authentication (401)
# ---------------------------------------------------------------------------
def get_auth():
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized X-User-Role")
    return role, user_id


# ---------------------------------------------------------------------------
# Authorization (403)
# ---------------------------------------------------------------------------
def require_roles(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


def forbidden():
    raise ApiError("ERR_UNAUTHORIZED", 403, "Not permitted")


# ---------------------------------------------------------------------------
# Existence (404)
# ---------------------------------------------------------------------------
def find_or_404(collection, ident):
    rec = collection.get(ident)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return rec


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate_params():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def apply_pagination(items, limit, offset):
    total = len(items)
    page = items[offset: offset + limit]
    return page, total
