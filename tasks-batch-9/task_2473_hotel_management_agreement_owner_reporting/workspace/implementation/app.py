"""Hotel Management Agreement & Owner Reporting API.

Flask application factory and process entry point.  All state lives in memory
(see db.py) and the store starts empty on every boot: nothing is seeded.
"""

import os
import sys

from flask import Flask
from werkzeug.exceptions import HTTPException

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from errors import ApiError  # noqa: E402
from response import error  # noqa: E402
from routes import (  # noqa: E402
    agreements,
    budgets,
    claims,
    clock,
    disputes,
    packages,
    perf,
)

BLUEPRINTS = (
    agreements.bp,
    budgets.bp,
    packages.bp,
    perf.bp,
    disputes.bp,
    claims.bp,
    clock.bp,
)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error("ERR_NOT_FOUND", "Resource not found.", 404)
        if exc.code == 405:
            return error(
                "ERR_METHOD_NOT_ALLOWED", "Method not allowed for this resource.", 405
            )
        if exc.code == 400:
            return error(
                "ERR_INVALID_REQUEST", "Request body must be a JSON object.", 400
            )
        return error(
            "ERR_INTERNAL", exc.description or "Unexpected error.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error: %s", exc)
        return error("ERR_INTERNAL", "Unexpected server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=False, use_reloader=False)
