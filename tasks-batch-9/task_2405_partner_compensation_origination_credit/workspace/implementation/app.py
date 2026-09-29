"""Partner Compensation & Origination Credit API (Flask, in-memory)."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_body
from routes import (assessments, awards, ballots, claims, clock, contributions, cycles,
                    matters, partners, transitions)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for module in (cycles, partners, matters, contributions, claims, assessments,
                   ballots, awards, transitions, clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_body(exc.error_id, exc.message), exc.http_status

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        code = exc.code or 500
        mapping = {
            400: "ERR_INVALID_REQUEST",
            404: "ERR_NOT_FOUND",
            405: "ERR_METHOD_NOT_ALLOWED",
            415: "ERR_INVALID_REQUEST",
        }
        error_id = mapping.get(code, "ERR_INTERNAL")
        if code == 400:
            code = 422
        return error_body(error_id, exc.description or "Request could not be served."), code

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - safety net
        return error_body("ERR_INTERNAL", "Internal server error."), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
