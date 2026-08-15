"""Entry point: Flask app, error handlers, route registration.

In-memory only; every fresh process boots with an empty store (PRD §2).
"""

import os
import sys

from flask import Flask

# Ensure the implementation directory is importable regardless of caller cwd.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST  # noqa: E402
from response import error_response  # noqa: E402
from routes import (coop, members, suppliers, programs, enrollments, reports,  # noqa: E402
                    audits, accruals, distributions, clawbacks, holdbacks)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (coop, members, suppliers, programs, enrollments, reports,
                   audits, accruals, distributions, clawbacks, holdbacks):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        if isinstance(err, ApiError):
            return error_response(err)
        return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(500)
    def handle_500(err):
        original = getattr(err, "original_exception", None)
        if isinstance(original, ApiError):
            return error_response(original)
        return error_response(ApiError(ERR_INVALID_REQUEST, 500,
                                       "Internal server error"))

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    try:
        # Production WSGI server: robust under the parallel per-test-server
        # restart load of the benchmark harness (the Flask dev server can
        # drop keep-alive connections mid-test under host CPU contention).
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8, channel_timeout=30)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
