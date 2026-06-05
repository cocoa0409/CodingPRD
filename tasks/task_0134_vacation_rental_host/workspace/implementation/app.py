"""Vacation Rental Host API — Flask entry point.

In-memory only: the global Store in db.py is constructed fresh on every process
boot, so each start.sh re-invocation wipes all state. No seeding at startup.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.identity import bp as identity_bp
from routes.listings import bp as listings_bp
from routes.rate_plans import bp as rate_plans_bp
from routes.calendar_blocks import bp as calendar_blocks_bp
from routes.channels import bp as channels_bp
from routes.bookings import bp as bookings_bp
from routes.screening import bp as screening_bp
from routes.claims import bp as claims_bp
from routes.payouts import bp as payouts_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(identity_bp)
    app.register_blueprint(listings_bp)
    app.register_blueprint(rate_plans_bp)
    app.register_blueprint(calendar_blocks_bp)
    app.register_blueprint(channels_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(screening_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(payouts_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route / unmatched path id -> ERR_NOT_FOUND envelope.
        return error_response("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", 404, "method not allowed")

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        # Map any other werkzeug HTTP error (e.g. malformed JSON 400) to validation.
        if e.code == 404:
            return error_response("ERR_NOT_FOUND", 404, "resource not found")
        return error_response("ERR_VALIDATION", 422, e.description or "bad request")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Defensive: never leak a raw 500 in the wrong envelope.
        return error_response("ERR_VALIDATION", 422, str(e))

    return app


app = create_app()


if __name__ == "__main__":
    import time

    port = int(os.environ.get("PORT", "10000"))
    # Bind-retry loop: under per-test-server isolation the previous process may
    # not have fully released the port when this one boots on the same port,
    # producing a transient "address already in use" that the runner reports as
    # "could not be restarted". Retry briefly before giving up.
    last_err = None
    for _ in range(40):
        try:
            app.run(host="0.0.0.0", port=port, threaded=True)
            break
        except OSError as exc:  # EADDRINUSE and friends
            last_err = exc
            time.sleep(0.25)
    else:
        raise last_err
