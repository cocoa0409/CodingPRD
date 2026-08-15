"""Electrical Supply Distributor API — Flask entry point."""

from __future__ import annotations

import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.contractors import bp as contractors_bp
from routes.catalog import bp as catalog_bp
from routes.job_accounts import bp as job_accounts_bp
from routes.quotes import bp as quotes_bp
from routes.quote_lines import bp as quote_lines_bp
from routes.substitutions import bp as substitutions_bp
from routes.releases import bp as releases_bp
from routes.release_reads import bp as release_reads_bp
from routes.rebates import bp as rebates_bp
from routes.testdrive import bp as testdrive_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(contractors_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(job_accounts_bp)
    app.register_blueprint(quotes_bp)
    app.register_blueprint(quote_lines_bp)
    app.register_blueprint(substitutions_bp)
    app.register_blueprint(releases_bp)
    app.register_blueprint(release_reads_bp)
    app.register_blueprint(rebates_bp)
    app.register_blueprint(testdrive_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

    @app.errorhandler(500)
    def handle_500(err):
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    try:
        from waitress import serve

        serve(app, host="0.0.0.0", port=port)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
