"""Position Management & Headcount Planning API — Flask entry point.

In-memory only: the global Store in db.py is constructed fresh on every process
boot, so each start.sh re-invocation wipes all state. No seeding at startup.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.employees import bp as employees_bp
from routes.grades import bp as grades_bp
from routes.cost_centers import bp as cost_centers_bp
from routes.positions import bp as positions_bp
from routes.incumbents import bp as incumbents_bp
from routes.freeze_orders import bp as freeze_orders_bp
from routes.requisitions import bp as requisitions_bp
from routes.reclass_requests import bp as reclass_requests_bp
from routes.forecast_periods import bp as forecast_periods_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(employees_bp)
    app.register_blueprint(grades_bp)
    app.register_blueprint(cost_centers_bp)
    app.register_blueprint(positions_bp)
    app.register_blueprint(incumbents_bp)
    app.register_blueprint(freeze_orders_bp)
    app.register_blueprint(requisitions_bp)
    app.register_blueprint(reclass_requests_bp)
    app.register_blueprint(forecast_periods_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route / unmatched path id -> ERR_NOT_FOUND envelope.
        return error_response("ERR_NOT_FOUND", 404, "resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        # Method not allowed on a known path: treat as not found per envelope.
        return error_response("ERR_NOT_FOUND", 404, "method not allowed")

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        if e.code == 404:
            return error_response("ERR_NOT_FOUND", 404, "resource not found")
        # Malformed body / other 4xx werkzeug errors map to invalid request.
        return error_response("ERR_INVALID_REQUEST", 422, e.description or "bad request")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Defensive: never leak a raw 500 in the wrong envelope.
        return error_response("ERR_INVALID_REQUEST", 422, str(e))

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
        except OSError as exc:
            last_err = exc
            time.sleep(0.25)
    else:
        raise last_err
