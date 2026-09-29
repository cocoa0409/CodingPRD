"""Post-Election Audit & Recount Administration API.

Flask application factory and blueprint registration. All state lives in
process memory (see db.py); nothing is seeded and nothing is persisted, so a
fresh process always starts from an empty store.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.audits import bp as audits_bp
from routes.custody import bp as custody_bp
from routes.elections import bp as elections_bp
from routes.findings import bp as findings_bp
from routes.interpretations import bp as interpretations_bp
from routes.observers import bp as observers_bp
from routes.recounts import bp as recounts_bp
from routes.tallies import bp as tallies_bp
from routes.teams import bp as teams_bp

BLUEPRINTS = (
    elections_bp,
    custody_bp,
    audits_bp,
    teams_bp,
    tallies_bp,
    findings_bp,
    interpretations_bp,
    recounts_bp,
    observers_bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return error_response(
            "ERR_METHOD_NOT_ALLOWED", "Method not allowed for this path.", 405
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("Unhandled error")
        return error_response(
            "ERR_INTERNAL", "An unexpected internal error occurred.", 500
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
