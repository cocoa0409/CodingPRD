"""Statement Composition & Print/Mail Bureau API - application entrypoint.

State lives entirely in process memory (see core.Store); every boot therefore
starts from a completely empty system with the logical clock at 2026-08-01T00:00:00Z.
Nothing is seeded, preloaded or persisted anywhere.
"""
import os

from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException

from core import ApiError, ERROR_STATUS, error_response, meta_base, new_request_id
import routes_intake
import routes_jobs
import routes_pieces
import routes_ref


def _envelope_error(error_id, message, status):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_ref.bp)
    app.register_blueprint(routes_intake.bp)
    app.register_blueprint(routes_jobs.bp)
    app.register_blueprint(routes_pieces.bp)

    @app.before_request
    def _assign_request_id():
        g.api_request_id = new_request_id()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return _envelope_error("ERR_NOT_FOUND", "the requested resource does not exist", 404)
        if exc.code == 405:
            return _envelope_error(
                "ERR_METHOD_NOT_ALLOWED", "the HTTP method is not allowed for this resource", 405
            )
        if exc.code == 400:
            return _envelope_error("ERR_VALIDATION", "the request could not be understood", 422)
        if exc.code == 415:
            return _envelope_error("ERR_VALIDATION", "unsupported request content type", 422)
        return _envelope_error("ERR_VALIDATION", exc.description or "request failed", exc.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return _envelope_error("ERR_INTERNAL", "internal server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
