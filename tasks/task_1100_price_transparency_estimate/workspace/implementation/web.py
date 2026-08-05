"""Flask-facing helpers: response envelope, auth, body validation, pagination."""
from flask import request, jsonify

import core
from core import ApiError, err, request_id, render_dt, wall_now


# ----------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ----------------------------------------------------------------------------
def _meta(extra=None):
    m = {"api_request_id": request_id(),
         "api_request_timestamp": render_dt(wall_now())}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object",
            "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total):
    meta = _meta({"limit": limit, "offset": offset, "total_count": total,
                  "has_more": offset + len(items) < total})
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return jsonify(error_body(e.error_id, e.message)), e.http_status

    @app.errorhandler(404)
    def _handle_404(e):
        return jsonify(error_body("ERR_VALIDATION", "Not found")), 404

    @app.errorhandler(405)
    def _handle_405(e):
        return jsonify(error_body("ERR_VALIDATION", "Method not allowed")), 405

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        if isinstance(e, ApiError):
            return jsonify(error_body(e.error_id, e.message)), e.http_status
        return jsonify(error_body("ERR_VALIDATION", str(e))), 400


# ----------------------------------------------------------------------------
# Auth (PRD §2.1, SCAFFOLD validations priority 1 & 2)
# ----------------------------------------------------------------------------
def authenticate(allowed_roles):
    """Priority 1: authentication. Priority 2 (role-level): authorization."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or role not in core.VALID_ROLES:
        err("ERR_UNAUTHENTICATED", "X-User-ID and a valid X-User-Role are required")
    if role not in allowed_roles:
        err("ERR_UNAUTHORIZED", f"Role {role} may not perform this operation")
    return user_id, role


def require_owner(role, user_id, patient_id):
    """PatientUser may only act on resources tied to the patient whose id == X-User-ID."""
    if role == "PatientUser" and patient_id != user_id:
        err("ERR_UNAUTHORIZED", "PatientUser does not own the target patient")


# ----------------------------------------------------------------------------
# Body access + field validation (ERR_VALIDATION, priority 3)
# ----------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        err("ERR_VALIDATION", "Request body must be a JSON object")
    return body


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        err("ERR_VALIDATION", f"{field} must be a non-empty string")
    return v


def req_int(body, field, minimum=None, maximum=None):
    v = body.get(field)
    if not _is_int(v):
        err("ERR_VALIDATION", f"{field} must be an integer")
    if minimum is not None and v < minimum:
        err("ERR_VALIDATION", f"{field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        err("ERR_VALIDATION", f"{field} must be <= {maximum}")
    return v


def req_number(body, field, minimum=None, maximum=None,
               min_exclusive=False, max_exclusive=False):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err("ERR_VALIDATION", f"{field} must be a number")
    if minimum is not None:
        if (v <= minimum) if min_exclusive else (v < minimum):
            err("ERR_VALIDATION", f"{field} out of range")
    if maximum is not None:
        if (v >= maximum) if max_exclusive else (v > maximum):
            err("ERR_VALIDATION", f"{field} out of range")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        err("ERR_VALIDATION", f"{field} must be one of {sorted(allowed)}")
    return v


def req_bool(body, field, default=None):
    if field not in body or body.get(field) is None:
        if default is not None:
            return default
        err("ERR_VALIDATION", f"{field} is required")
    v = body.get(field)
    if not isinstance(v, bool):
        err("ERR_VALIDATION", f"{field} must be a boolean")
    return v


def opt_bool(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, bool):
        err("ERR_VALIDATION", f"{field} must be a boolean")
    return v


def req_datetime(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        err("ERR_VALIDATION", f"{field} must be an ISO 8601 datetime string")
    try:
        core.parse_iso(v)
    except Exception:
        err("ERR_VALIDATION", f"{field} is not a valid ISO 8601 datetime")
    return v


# ----------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ----------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            err("ERR_VALIDATION", "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            err("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(records, serialize_fn):
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([serialize_fn(r) for r in page], limit, offset, total)
