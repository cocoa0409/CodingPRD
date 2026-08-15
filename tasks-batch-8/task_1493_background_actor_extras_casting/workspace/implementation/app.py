"""Central Casting style background extras casting API — Flask entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import routes_actors
    import routes_batches
    import routes_bookings
    import routes_bumps
    import routes_calls
    import routes_clock
    import routes_events
    import routes_planning
    import routes_productions
    import routes_replacement
    import routes_vouchers

    for module in (
        routes_productions,
        routes_actors,
        routes_calls,
        routes_planning,
        routes_bookings,
        routes_events,
        routes_vouchers,
        routes_bumps,
        routes_batches,
        routes_replacement,
        routes_clock,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.status)

    @app.errorhandler(HTTPException)
    def handle_http_error(err):
        # Unknown paths / wrong methods still answer in the standard envelope.
        error_id = "ERR_NOT_FOUND" if err.code == 404 else "ERR_VALIDATION"
        message = err.name if err.name else "HTTP error"
        return error_response(error_id, message, err.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
