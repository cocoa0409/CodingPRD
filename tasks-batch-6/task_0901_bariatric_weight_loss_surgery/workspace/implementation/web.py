"""Response envelope, error type, auth, and body-validation helpers."""
import random
import string
from flask import jsonify, request

from models import now_iso

ALL_ROLES = {"ProgramCoordinator", "Dietitian", "BehavioralHealthClinician",
             "BillingSpecialist", "Surgeon", "SystemAdmin"}


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    rt = "array" if isinstance(data, list) else "object"
    body = {"meta": _meta(), "response_type": rt, "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta({"limit": limit, "offset": offset, "total_count": total_count,
                  "has_more": offset + len(items) < total_count})
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def err_response(e: ApiError):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http_status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    """Validate headers (401), then role permission (403). Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid auth headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
    return user_id, role


# ---------------------------------------------------------------------------
# Body parsing / validation
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return body


def _fail(msg):
    raise ApiError("ERR_VALIDATION", 400, msg)


def req_str(body, name):
    if name not in body or body[name] is None:
        _fail(f"Missing required field: {name}")
    v = body[name]
    if not isinstance(v, str) or v == "":
        _fail(f"Field {name} must be a non-empty string")
    return v


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str):
        _fail(f"Field {name} must be a string")
    return v


def req_enum(body, name, allowed):
    v = req_str(body, name)
    if v not in allowed:
        _fail(f"Field {name} must be one of {sorted(allowed)}")
    return v


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_number(body, name, gt=None, ge=None, le=None):
    if name not in body or body[name] is None:
        _fail(f"Missing required field: {name}")
    v = body[name]
    if not _is_number(v):
        _fail(f"Field {name} must be a number")
    if gt is not None and not v > gt:
        _fail(f"Field {name} must be > {gt}")
    if ge is not None and not v >= ge:
        _fail(f"Field {name} must be >= {ge}")
    if le is not None and not v <= le:
        _fail(f"Field {name} must be <= {le}")
    return v


def req_int(body, name, ge=None, le=None):
    if name not in body or body[name] is None:
        _fail(f"Missing required field: {name}")
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        _fail(f"Field {name} must be an integer")
    if ge is not None and not v >= ge:
        _fail(f"Field {name} must be >= {ge}")
    if le is not None and not v <= le:
        _fail(f"Field {name} must be <= {le}")
    return v


def opt_int(body, name, default=None, ge=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        _fail(f"Field {name} must be an integer")
    if ge is not None and not v >= ge:
        _fail(f"Field {name} must be >= {ge}")
    return v


def req_bool(body, name):
    if name not in body or body[name] is None:
        _fail(f"Missing required field: {name}")
    v = body[name]
    if not isinstance(v, bool):
        _fail(f"Field {name} must be a boolean")
    return v


def opt_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        _fail(f"Field {name} must be a boolean")
    return v


def req_str_array(body, name, allowed):
    if name not in body or body[name] is None:
        _fail(f"Missing required field: {name}")
    v = body[name]
    if not isinstance(v, list):
        _fail(f"Field {name} must be an array")
    for item in v:
        if not isinstance(item, str) or item not in allowed:
            _fail(f"Field {name} items must each be one of {sorted(allowed)}")
    return v


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            _fail("limit must be an integer")
        if limit < 1 or limit > 100:
            _fail("limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            _fail("offset must be an integer")
        if offset < 0:
            _fail("offset must be >= 0")
    return limit, offset


def paginate(rows):
    """rows: list of stored entity dicts. Sorts by (created_at, _seq)."""
    limit, offset = pagination()
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, limit, offset, total
