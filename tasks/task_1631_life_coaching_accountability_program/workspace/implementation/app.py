"""Entry point: Flask app, error handlers, blueprint registration.

All state is in-memory (db.store) and starts empty on every boot — no seeding,
no persistence. The logical clock boots at 2026-08-01T00:00:00Z (PRD §2.5).
"""
import os

from flask import Flask

from envelope import error
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from routes import infra, coaches, clients, tiers, discovery, enrollments, sessions, goals, cohorts, testimonials, refunds


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_404(err):
        return error(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(err):
        return error(ERR_INVALID_REQUEST, 400, "Method not allowed for this path")

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error(ERR_INVALID_REQUEST, 400, "Unexpected error: %s" % err)

    for module in (infra, coaches, clients, tiers, discovery, enrollments,
                   sessions, goals, cohorts, testimonials, refunds):
        app.register_blueprint(module.bp, url_prefix="/coaching")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
