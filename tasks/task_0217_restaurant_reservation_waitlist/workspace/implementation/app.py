"""Restaurant Reservation & Waitlist API — Flask entry point.

In-memory store only; the process holds no durable state and boots empty on
every launch. Registers all resource blueprints, the standard response
envelope error handlers, and a request-level system-expiry sweep.
"""
import os

from flask import Flask, request

from errors import ApiError
from response import error_response
from services.system_expiry import sweep_all

# Route blueprints
from routes.restaurants import bp as restaurants_bp
from routes.dining_areas import bp as dining_areas_bp
from routes.tables import bp as tables_bp
from routes.service_periods import bp as service_periods_bp
from routes.customers import bp as customers_bp
from routes.reservations import bp as reservations_bp
from routes.deposit_holds import bp as deposit_holds_bp
from routes.special_requests import bp as special_requests_bp
from routes.notifications import bp as notifications_bp
from routes.waitlist import bp as waitlist_bp
from routes.private_dining import bp as private_dining_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    @app.before_request
    def _sweep_due_system_transitions():
        # Apply any clock-advance system transitions (waitlist EXPIRED, hold
        # EXPIRED) before handling the request, except for the clock endpoint
        # itself which sweeps after pinning the clock.
        if request.path != "/_clock/set_current_utc":
            sweep_all()

    for bp in (
        restaurants_bp, dining_areas_bp, tables_bp, service_periods_bp,
        customers_bp, reservations_bp, deposit_holds_bp, special_requests_bp,
        notifications_bp, waitlist_bp, private_dining_bp, clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def _handle_api_error(exc):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _handle_404(exc):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def _handle_405(exc):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(400)
    def _handle_400(exc):
        return error_response("ERR_VALIDATION", "malformed request", 422)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return error_response(exc.error_id, exc.message, exc.http_status)
        return error_response("ERR_VALIDATION", str(exc), 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Serve under waitress, a production-grade pure-Python WSGI server. The
    # benchmark reboots the server before every test under heavy concurrent load
    # (8 parallel rounds), and the Werkzeug dev server occasionally drops an
    # established connection mid-request under that pressure (a BadStatusLine on
    # the client). Waitress's threaded connection handling is robust to that
    # churn. Fall back to the dev server only if waitress is unavailable.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8,
              channel_timeout=120, _quiet=True)
    except ImportError:  # pragma: no cover
        app.run(host="0.0.0.0", port=port, threaded=True)
