"""Campus Shuttle Dispatch API — Flask entrypoint."""
import os

from flask import Flask

from errors import APIError
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Register blueprints
    from routes.routes_bp import bp as routes_bp
    from routes.stops import bp as stops_bp
    from routes.vehicles import bp as vehicles_bp
    from routes.drivers import bp as drivers_bp
    from routes.run_sheets import bp as run_sheets_bp
    from routes.reservations import bp as reservations_bp
    from routes.ridership import bp as ridership_bp
    from routes.bills import bp as bills_bp
    from routes.audit_logs import bp as audit_bp
    from routes.clock_advance import bp as clock_bp

    for bp in (routes_bp, stops_bp, vehicles_bp, drivers_bp,
               run_sheets_bp, reservations_bp, ridership_bp,
               bills_bp, audit_bp, clock_bp):
        app.register_blueprint(bp)

    @app.errorhandler(APIError)
    def handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND",
                              "Route or resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND",
                              "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_VALIDATION", "Bad request", 422)

    @app.errorhandler(Exception)
    def handle_exc(e):
        if isinstance(e, APIError):
            return error_response(e.error_id, e.message, e.http_status)
        import traceback
        traceback.print_exc()
        return error_response("ERR_VALIDATION", str(e) or "Internal error", 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
