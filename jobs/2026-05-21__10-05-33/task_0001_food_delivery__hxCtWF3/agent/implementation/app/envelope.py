"""Standard success and error response envelopes."""
from flask import jsonify, g

from .clock import format_iso
from .errors import ApiError, ERROR_TABLE
from .ids import new_request_id


def _meta(extra: dict | None = None) -> dict:
    meta = {
        "api_request_id": g.api_request_id,
        "api_request_timestamp": g.api_request_timestamp,
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status: int = 200, response_type: str | None = None, page: dict | None = None):
    if response_type is None:
        response_type = "array" if isinstance(data, list) else "object"
    payload = {
        "meta": _meta(page),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    resp = jsonify(payload)
    resp.status_code = status
    return resp


def error_response(error_id: str, message: str = "", http_status: int | None = None):
    status = http_status or ERROR_TABLE.get(error_id, 400)
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    resp = jsonify(payload)
    resp.status_code = status
    return resp


def install_request_context(app):
    @app.before_request
    def _stamp_request():
        from .server import clock
        g.api_request_id = new_request_id()
        g.api_request_timestamp = format_iso(clock.now())

    @app.errorhandler(ApiError)
    def _handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def _flask_404(err):  # noqa: ARG001
        return error_response("ERR_NOT_FOUND", "route not found", 404)

    @app.errorhandler(405)
    def _flask_405(err):  # noqa: ARG001
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(400)
    def _flask_400(err):  # noqa: ARG001
        return error_response("ERR_VALIDATION", "invalid request body", 422)

    @app.errorhandler(Exception)
    def _flask_500(err):
        return error_response("ERR_VALIDATION", f"internal error: {err}", 500)
