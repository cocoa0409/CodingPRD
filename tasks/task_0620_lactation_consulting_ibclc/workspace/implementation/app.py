"""Lactation Consulting & Breastfeeding Support (IBCLC) API — entry point.

In-memory only; no seeding. Boots clean on every process start.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.practices import bp as practices_bp
from routes.catalog import bp as catalog_bp
from routes.clients import bp as clients_bp
from routes.consults import bp as consults_bp
from routes.feeding_assessments import bp as feeding_bp
from routes.follow_up_plans import bp as plans_bp
from routes.superbills import bp as superbills_bp
from routes.dme import bp as dme_bp
from routes.referrals import bp as referrals_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(practices_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(consults_bp)
    app.register_blueprint(feeding_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(superbills_bp)
    app.register_blueprint(dme_bp)
    app.register_blueprint(referrals_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route / path resource not found.
        return error_response("ERR_RESOURCE_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_RESOURCE_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        # Map any other werkzeug HTTP errors (e.g. malformed JSON) into the
        # envelope. Default to a 400 invalid-request shape.
        code = exc.code or 500
        if code == 400:
            return error_response("ERR_INVALID_REQUEST", "Bad request", 400)
        return error_response("ERR_INVALID_REQUEST", exc.description or "Error", code)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_INVALID_REQUEST", "Internal error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
