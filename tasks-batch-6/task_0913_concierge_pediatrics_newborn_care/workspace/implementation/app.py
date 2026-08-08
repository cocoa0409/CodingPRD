"""Concierge Pediatrics & Newborn Care API — entry point.

In-memory only; the store is empty on every boot and nothing is ever seeded.
"""
import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import routes_benefits
import routes_billing
import routes_clinical
import routes_core
import routes_encounters
import routes_forms
import routes_membership
from envelope import error_response
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_membership.bp)
    app.register_blueprint(routes_benefits.bp)
    app.register_blueprint(routes_clinical.bp)
    app.register_blueprint(routes_encounters.bp)
    app.register_blueprint(routes_billing.bp)
    app.register_blueprint(routes_forms.bp)

    @app.before_request
    def _init_request_state():
        g.touched = set()

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            return error_response(
                "ERR_RESOURCE_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if exc.code == 405:
            return error_response(
                "ERR_RESOURCE_NOT_FOUND", "The requested resource does not exist.", 404
            )
        if exc.code == 400:
            return error_response(
                "ERR_VALIDATION", "The request payload failed validation.", 400
            )
        return error_response("ERR_VALIDATION", exc.description or "Request failed.", exc.code)

    @app.errorhandler(Exception)
    def _unexpected(exc):  # pragma: no cover - safety net
        return error_response("ERR_VALIDATION", "Unexpected server error: %s" % exc, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
