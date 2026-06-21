"""Water & Sewer Utility Billing API — Flask entry point.

Storage is in-memory only and starts EMPTY on every boot. No entities are
seeded, preloaded, or hardcoded. Tests build all state via the API surface.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import db
import errors
from response import error_response

# Blueprints
from routes.rate_schedules import bp as rate_schedules_bp
from routes.accounts import bp as accounts_bp
from routes.meters import bp as meters_bp
from routes.billing_cycles import bp as billing_cycles_bp
from routes.bills import bp as bills_bp
from routes.budget_plans import bp as budget_plans_bp
from routes.payments import bp as payments_bp
from routes.assistance import bp as assistance_bp
from routes.leak_adjustments import bp as leak_adjustments_bp
from routes.shutoff_orders import bp as shutoff_orders_bp
from routes.moratoriums import bp as moratoriums_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        rate_schedules_bp, accounts_bp, meters_bp, billing_cycles_bp, bills_bp,
        budget_plans_bp, payments_bp, assistance_bp, leak_adjustments_bp,
        shutoff_orders_bp, moratoriums_bp, clock_bp,
    ):
        app.register_blueprint(bp)

    # ---- Error handlers: every error uses the standard envelope (PRD §2.2) ----
    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(errors.ERR_NOT_FOUND, "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        # Method not allowed on an existing path — closest catalog entry.
        return error_response(errors.ERR_NOT_FOUND, "Method not allowed.", 404)

    @app.errorhandler(415)
    def handle_415(e):
        return error_response(errors.ERR_INVALID_REQUEST, "Unsupported media type.", 422)

    @app.errorhandler(400)
    def handle_400(e):
        # Malformed JSON body and similar.
        return error_response(errors.ERR_INVALID_REQUEST, "Malformed request.", 422)

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Fallback for other werkzeug HTTP errors.
        return error_response(errors.ERR_INVALID_REQUEST, e.description or "Request error.", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Never leak a stack trace as a bare 500 without the envelope.
        return error_response("ERR_INTERNAL", "Internal server error: %s" % e, 500)

    return app


# Build the app and wipe the store at process start (fresh, empty, no seeding).
db.reset()
app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
