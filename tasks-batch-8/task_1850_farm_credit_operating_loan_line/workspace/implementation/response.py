"""Response envelope helpers (PRD 2.2 / scaffold 1.0)."""
from flask import jsonify

from errors import ApiError
from util import new_request_id, wall_ts3


def meta():
    return {"api_request_id": new_request_id(), "api_request_timestamp": wall_ts3()}


def ok(data, code=200, response_type="object", pagination=None):
    m = meta()
    if pagination is not None:
        m["limit"] = pagination["limit"]
        m["offset"] = pagination["offset"]
        m["total_count"] = pagination["total_count"]
        m["has_more"] = pagination["has_more"]
    payload = {"meta": m, "response_type": response_type, "data": data}
    resp = jsonify(payload)
    resp.status_code = code
    return resp


def ok_object(data, code=200):
    return ok(data, code=code, response_type="object")


def ok_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    return ok(items, code=200, response_type="array",
              pagination={"limit": limit, "offset": offset,
                          "total_count": total_count, "has_more": has_more})


def err_response(api_err):
    payload = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    resp = jsonify(payload)
    resp.status_code = api_err.http_status
    return resp


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return err_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(e):
        return err_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))

    @app.errorhandler(Exception)
    def handle_exception(e):
        return err_response(ApiError("ERR_INVALID_REQUEST", 400, str(e)))
