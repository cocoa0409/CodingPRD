"""Garage Door Install & Repair API — Flask entry point.

In-memory storage only; the store starts empty on every boot (no seeding).
Boots a fresh process per test under per-test-server isolation.
"""
import os

from flask import Flask, request

import db
import errors
from response import error_response
from routes.admin import bp as admin_bp
from routes.callbacks import bp as callbacks_bp
from routes.catalog import bp as catalog_bp
from routes.financing import bp as financing_bp
from routes.jobs import bp as jobs_bp
from routes.people import bp as people_bp
from routes.quotes import bp as quotes_bp
from routes.reservations import bp as reservations_bp
from routes.warranty import bp as warranty_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Fresh, empty store on boot (defensive — module-level dicts already empty).
    db.reset()

    app.register_blueprint(catalog_bp)
    app.register_blueprint(people_bp)
    app.register_blueprint(quotes_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(warranty_bp)
    app.register_blueprint(financing_bp)
    app.register_blueprint(callbacks_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, errors.ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", str(e), 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
