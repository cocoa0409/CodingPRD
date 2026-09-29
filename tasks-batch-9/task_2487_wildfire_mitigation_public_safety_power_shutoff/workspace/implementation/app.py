"""Wildfire Mitigation & Public Safety Power Shutoff API.

Flask application factory. All state lives in process memory (see db.py) and is
therefore wiped on every boot: nothing is seeded, preloaded or hardcoded.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import routes
from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.before_request
    def _prepare_request():
        # Version counters bump at most once per row per request (PRD 2.10).
        g.touched = set()

    @app.errorhandler(ApiError)
    def _api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        return error_response(
            "ERR_INVALID_REQUEST",
            error.description or "The request could not be handled.",
            error.code or 400,
        )

    @app.errorhandler(Exception)
    def _unexpected(error):  # pragma: no cover - defensive
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error.", 500)

    routes.register_all(app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
