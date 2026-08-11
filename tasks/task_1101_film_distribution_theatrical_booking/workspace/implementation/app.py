"""Flask entry point: error handlers, route registration, server boot."""
import os
import sys

from flask import Flask, jsonify

from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.errorhandler(ApiError)
    def _api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _not_found(e):
        return error_response("ERR_NOT_FOUND", "Resource not found at the specified path", 404)

    @app.errorhandler(405)
    def _method(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def _unhandled(e):
        # Log and return 400 as a safe default; Flask's own HTTPExceptions have codes.
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return error_response("ERR_INVALID_REQUEST", e.description or "Bad request", 400)
        print(f"Unhandled: {type(e).__name__}: {e}", file=sys.stderr)
        import traceback; traceback.print_exc()
        return error_response("ERR_INVALID_REQUEST", "Internal error", 400)

    # Register route blueprints
    from routes.distributors import bp as distributors_bp
    from routes.films import bp as films_bp
    from routes.markets import bp as markets_bp
    from routes.theatres import bp as theatres_bp
    from routes.aggregate_deals import bp as agg_bp
    from routes.bookings import bp as bookings_bp
    from routes.dcp import bp as dcp_bp
    from routes.kdm import bp as kdm_bp
    from routes.reports import bp as reports_bp
    from routes.settlements import bp as settlements_bp
    from routes.marketing import bp as marketing_bp
    from routes.zones import bp as zones_bp
    from routes.ancillary import bp as ancillary_bp
    from routes.clock import bp as clock_bp

    for bp in (distributors_bp, films_bp, markets_bp, theatres_bp, agg_bp, bookings_bp,
               dcp_bp, kdm_bp, reports_bp, settlements_bp, marketing_bp, zones_bp,
               ancillary_bp, clock_bp):
        app.register_blueprint(bp)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
