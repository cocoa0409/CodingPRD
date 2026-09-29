"""Public EV Charging Network Reliability and Uptime API.

In-memory Flask service.  Every process starts with empty stores: no seeded
entities, and the logical clock at its default reading (PRD §2.4).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import ALL_BLUEPRINTS


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "The requested resource does not exist.", 404)
        if exc.code == 405:
            return error_response("ERR_METHOD_NOT_ALLOWED",
                                  "That method is not allowed on this path.", 405)
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST",
                                  "The request could not be parsed.", 400)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                              exc.code or 400)

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            debug=False, threaded=True, use_reloader=False)
