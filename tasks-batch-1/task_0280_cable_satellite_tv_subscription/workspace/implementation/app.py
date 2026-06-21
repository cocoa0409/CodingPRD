"""Cable / Satellite TV Subscription API — Flask entry point.

In-memory storage only; nothing seeded at startup. The store lives in db.py
module globals and is wiped on every fresh process boot. start.sh re-launches
this process before every test under per-test-server isolation.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
from response import error_response

from routes.catalog import bp as catalog_bp
from routes.lookups import bp as lookups_bp
from routes.accounts import bp as accounts_bp
from routes.subscriptions import bp as subscriptions_bp
from routes.addons import bp as addons_bp
from routes.equipment import bp as equipment_bp
from routes.visits import bp as visits_bp
from routes.promotions import bp as promotions_bp
from routes.billing import bp as billing_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(lookups_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(subscriptions_bp)
    app.register_blueprint(addons_bp)
    app.register_blueprint(equipment_bp)
    app.register_blueprint(visits_bp)
    app.register_blueprint(promotions_bp)
    app.register_blueprint(billing_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unknown route — return the envelope with a generic not-found error.
        return error_response("ERR_ACCOUNT_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_VALIDATION", "Method not allowed", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        # Map any other werkzeug HTTP error into the standard envelope.
        if isinstance(exc, errors.ApiError):  # defensive
            return error_response(exc.error_id, exc.message, exc.http_status)
        code = exc.code or 500
        if code == 400:
            return error_response(errors.ERR_INVALID_REQUEST, "Bad request", 422)
        return error_response("ERR_VALIDATION", exc.description or "Error", code)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return error_response("ERR_VALIDATION", "Internal error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
