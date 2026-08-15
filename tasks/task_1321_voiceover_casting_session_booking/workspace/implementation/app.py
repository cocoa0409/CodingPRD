"""Entry point: Flask app, error handlers, route registration.

All routes are mounted under /api (scaffold api_prefix). The store starts empty
on every boot; only the ClockState singleton is initialized (PRD §2.5).
"""
import os

from flask import Flask

from db import init_store
from errors import ApiError
from response import err


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes import (
        auditions, clients, clock, conflicts, deliveries, invoices,
        projects, sessions, studios, talents, usage_terms,
    )
    for module in (clock, talents, clients, projects, auditions, studios,
                   sessions, usage_terms, deliveries, invoices, conflicts):
        app.register_blueprint(module.bp, url_prefix="/api")

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err(e.error_id, e.status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return err("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return err("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return err(e.error_id, e.status, e.message)
        return err("ERR_INVALID_REQUEST", 400, str(e) or "Unexpected error")

    return app


init_store()
app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
