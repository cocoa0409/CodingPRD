"""Foodservice Equipment Manufacturing API — Flask entrypoint.

In-memory only: every boot starts with empty stores and the default logical clock.
Nothing is seeded, preloaded or persisted anywhere.
"""
import os
import threading

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError, default_message
from response import error_body
from routes import (
    build_lines,
    certification_listings,
    chain_accounts,
    chain_configurations,
    clock,
    connected_units,
    construction_programs,
    equipment_models,
    firmware_campaigns,
    performance_validations,
    production_slots,
    service_partners,
    site_orders,
    technician_certifications,
    warranty_claims,
)

BLUEPRINTS = (
    clock.bp,
    equipment_models.bp,
    certification_listings.bp,
    chain_accounts.bp,
    chain_configurations.bp,
    performance_validations.bp,
    construction_programs.bp,
    site_orders.bp,
    build_lines.bp,
    production_slots.bp,
    connected_units.bp,
    firmware_campaigns.bp,
    service_partners.bp,
    technician_certifications.bp,
    warranty_claims.bp,
)

_write_lock = threading.RLock()


class SerializingMiddleware(object):
    """Serialise requests so multi-entity cascades are atomic (PRD Section 2.11)."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        with _write_lock:
            result = self.wsgi_app(environ, start_response)
            if isinstance(result, list):
                return result
            return list(result)


def _error(error_id, message, status):
    return jsonify(error_body(error_id, message)), status


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return _error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return _error("ERR_CHAIN_RESOURCE_NOT_FOUND", "unknown route", 404)
        if exc.code == 405:
            return _error("ERR_ROLE_NOT_PERMITTED", "method not allowed on this path", 405)
        if exc.code in (400, 415):
            return _error("ERR_INVALID_REQUEST", default_message("ERR_INVALID_REQUEST"), 400)
        return _error("ERR_INVALID_REQUEST", exc.description or "request failed", exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):  # pragma: no cover - defensive
        app.logger.exception("unhandled error: %s", exc)
        return _error("ERR_INVALID_REQUEST", "unexpected server error", 500)

    app.wsgi_app = SerializingMiddleware(app.wsgi_app)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, use_reloader=False)
