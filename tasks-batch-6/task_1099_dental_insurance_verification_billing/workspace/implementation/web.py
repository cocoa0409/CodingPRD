"""Flask-facing helpers: response envelope, auth extraction, role checks, pagination."""
from flask import request, jsonify

import core
from core import ApiError, err, request_id, render_dt, wall_now


def _meta(extra=None):
    m = {"api_request_id": request_id(), "api_request_timestamp": render_dt(wall_now())}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def empty_ok():
    return ok({}, 200)


def ok_list(items, limit, offset, total):
    meta = _meta({"limit": limit, "offset": offset, "total_count": total,
                  "has_more": offset + len(items) < total})
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return body


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return jsonify(error_body(e.error_id, e.message)), e.http_status

    @app.errorhandler(404)
    def _handle_404(e):
        return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404

    @app.errorhandler(405)
    def _handle_405(e):
        return jsonify(error_body("ERR_NOT_FOUND", "Method not allowed")), 404

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        if isinstance(e, ApiError):
            return jsonify(error_body(e.error_id, e.message)), e.http_status
        return jsonify(error_body("ERR_INVALID_REQUEST", str(e))), 400


# ----------------------------------------------------------------------------
# Auth
# ----------------------------------------------------------------------------
def auth(allowed_roles):
    """Validate user-context headers (priority 1) and role permission (priority 2)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or role not in core.VALID_ROLES:
        err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and a valid X-User-Role are required")
    if role not in allowed_roles:
        err("ERR_FORBIDDEN_FOR_ROLE", f"Role {role} may not perform this operation")
    return user_id, role


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


# ----------------------------------------------------------------------------
# Pagination + filtering
# ----------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args:
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(records, serialize):
    """records: iterable of raw records (already filtered). Sort by creation order."""
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([serialize(r) for r in page], limit, offset, total)


def qfilter(records, field, value, cast=str):
    if value is None:
        return records
    return [r for r in records if str(r.get(field)) == str(value)]
