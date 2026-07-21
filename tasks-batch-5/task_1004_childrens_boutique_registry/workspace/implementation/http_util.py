"""Response envelope, error type, error handlers, and auth/RBAC helpers."""
from flask import jsonify, request

import db

RECOGNIZED_ROLES = {"Anonymous", "Customer", "StoreStaff", "PlatformAdmin"}


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def _meta(pagination=None):
    m = {
        "api_request_id": db.request_id(),
        "api_request_timestamp": db.now_iso(),
    }
    if pagination:
        m.update(pagination)
    return m


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def _handle_404(exc):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def _handle_405(exc):
        return error_response("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed")

    @app.errorhandler(Exception)
    def _handle_other(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.http_status, exc.message)
        return error_response("ERR_INTERNAL", 500, str(exc))


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def get_role():
    return request.headers.get("X-User-Role")


def get_user_id():
    return request.headers.get("X-User-ID")


def require_auth(allowed_roles):
    """Validate authentication + authorization against the allowed role set.

    If Anonymous is among allowed roles the endpoint is public: any caller is
    accepted (no 401/403). Otherwise a recognized role is required (else 401)
    and it must be one of the allowed roles (else 403).
    Returns the effective role string.
    """
    role = get_role()
    if "Anonymous" in allowed_roles:
        return role
    if role is None or role not in RECOGNIZED_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized X-User-Role")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
    return role


def require_owner(role, owner_fk):
    """For entity-backed Customer actions on an owned resource, enforce that
    X-User-ID equals the owner foreign key. Opaque roles are exempt."""
    if role == "Customer":
        if get_user_id() != owner_fk:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not the resource owner")


def get_json_body():
    data = request.get_json(silent=True, force=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 422, "Request body must be a JSON object")
    return data
