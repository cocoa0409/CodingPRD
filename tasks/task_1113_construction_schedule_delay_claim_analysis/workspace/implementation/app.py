"""Construction Schedule & Delay Claim Analysis API — entry point.

Flask app wiring: error handlers (standard error envelope), blueprint
registration, foreground server on 0.0.0.0:$PORT (default 10000).
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
)
from response import error_response


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    from routes.clock import bp as clock_bp
    from routes.projects import bp as projects_bp
    from routes.schedule_versions import bp as versions_bp
    from routes.activities import bp as activities_bp
    from routes.relationships import bp as relationships_bp
    from routes.progress import bp as progress_bp
    from routes.delay_events import bp as delay_events_bp
    from routes.eot import bp as eot_bp
    from routes.acceleration import bp as acceleration_bp
    from routes.lda import bp as lda_bp
    from routes.flat import bp as flat_bp

    for bp in (clock_bp, projects_bp, versions_bp, activities_bp,
               relationships_bp, progress_bp, delay_events_bp, eot_bp,
               acceleration_bp, lda_bp, flat_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, 404,
                              "Path-referenced resource does not exist")

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_INVALID_REQUEST, 405,
                              "Method not allowed for this path")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, HTTPException):
            return error_response(ERR_INVALID_REQUEST, err.code,
                                  err.description or "HTTP error")
        return error_response(ERR_INVALID_REQUEST, 500,
                              "Internal server error: %s" % err)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
