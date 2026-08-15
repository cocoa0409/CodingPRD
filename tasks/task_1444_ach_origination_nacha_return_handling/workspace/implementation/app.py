"""ACH ODFI Origination & NACHA Return Handling API — Flask entry point."""

from __future__ import annotations

import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.clock import bp as clock_bp
from routes.originators import bp as originators_bp
from routes.risk_cases import bp as risk_cases_bp
from routes.files import bp as files_bp
from routes.entries import bp as entries_bp
from routes.nocs import bp as nocs_bp
from routes.reversals import bp as reversals_bp
from routes.batches import bp as batches_bp
from routes.windows import bp as windows_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(originators_bp)
    app.register_blueprint(risk_cases_bp)
    app.register_blueprint(files_bp)
    app.register_blueprint(entries_bp)
    app.register_blueprint(nocs_bp)
    app.register_blueprint(reversals_bp)
    app.register_blueprint(batches_bp)
    app.register_blueprint(windows_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8, channel_timeout=30)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
