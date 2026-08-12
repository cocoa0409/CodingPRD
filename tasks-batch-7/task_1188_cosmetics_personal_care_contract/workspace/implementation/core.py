"""Core plumbing: error type, response envelope, auth decorator, validation
helpers, pagination, and common-field lifecycle (id/created_at/updated_at/version)."""
import functools
import secrets

from flask import g, jsonify, request

from store import db, iso_now, new_id

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err(error_id, status, message):
    raise ApiError(error_id, status, message)


# ---------------------------------------------------------------------------
# Response envelope (per SCAFFOLD response_envelope / PRD section 2.2)
# ---------------------------------------------------------------------------


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(10),
        "api_request_timestamp": iso_now(),
    }


def success(data, status=200, response_type="object", pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


def error_response(exc):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": exc.error_id, "message": exc.message},
    }
    return jsonify(body), exc.status


# ---------------------------------------------------------------------------
# Auth (PRD section 2.1)
# ---------------------------------------------------------------------------

ROLES = {
    "CustomerRep",
    "FormulationChemist",
    "RegulatoryAffairs",
    "QAManager",
    "ProductionPlanner",
    "PlantDirector",
}


def require_roles(*roles):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                err("ERR_UNAUTHENTICATED", 401,
                    "Missing or unknown X-User-Role / X-User-ID headers")
            if roles and role not in roles:
                err("ERR_FORBIDDEN_ROLE", 403,
                    "Acting role is not permitted for this endpoint")
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


# ---------------------------------------------------------------------------
# Request-body validation helpers
# ---------------------------------------------------------------------------


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return data


def get_required(data, field):
    if field not in data or data[field] is None:
        err("ERR_VALIDATION", 400, f"Missing required field: {field}")
    return data[field]


def check_enum(value, allowed, field):
    if value not in allowed:
        err("ERR_VALIDATION", 400, f"Invalid value for {field}")
    return value


def check_int(value, field, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        err("ERR_VALIDATION", 400, f"Field {field} must be an integer")
    if minimum is not None and value < minimum:
        err("ERR_VALIDATION", 400, f"Field {field} must be >= {minimum}")
    return value


def check_number(value, field, minimum=None, maximum=None, exclusive_min=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        err("ERR_VALIDATION", 400, f"Field {field} must be a number")
    if minimum is not None:
        if exclusive_min and not value > minimum:
            err("ERR_VALIDATION", 400, f"Field {field} must be > {minimum}")
        if not exclusive_min and value < minimum:
            err("ERR_VALIDATION", 400, f"Field {field} must be >= {minimum}")
    if maximum is not None and value > maximum:
        err("ERR_VALIDATION", 400, f"Field {field} must be <= {maximum}")
    return value


def check_string(value, field):
    if not isinstance(value, str):
        err("ERR_VALIDATION", 400, f"Field {field} must be a string")
    return value


def check_bool(value, field):
    if not isinstance(value, bool):
        err("ERR_VALIDATION", 400, f"Field {field} must be a boolean")
    return value


# ---------------------------------------------------------------------------
# Pagination (PRD section 2.3): limit default 10 min 1 max 100; offset default 0
# ---------------------------------------------------------------------------


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(100, limit))
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)
    return limit, offset


def list_page(items, serializer):
    ordered = sorted(items, key=lambda e: e["_seq"])  # created_at ascending
    limit, offset = pagination_params()
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return success([serializer(i) for i in page], response_type="array", pagination=pag)


# ---------------------------------------------------------------------------
# Common fields (PRD section 2.4)
# ---------------------------------------------------------------------------


def new_entity():
    ts = iso_now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(ent):
    ent["updated_at"] = iso_now()
    ent["version"] = ent.get("version", 1) + 1
