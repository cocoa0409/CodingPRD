"""Flask entrypoint for the Airport Meet Assist API."""
import os

from flask import Flask

from errors import ApiError, bad_request
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    from routes.airports import bp as airports_bp
    from routes.passengers import bp as passengers_bp
    from routes.agents import bp as agents_bp
    from routes.requests import bp as requests_bp
    from routes.dispatch import bp as dispatch_bp
    from routes.incidents import bp as incidents_bp
    from routes.invoices import bp as invoices_bp
    from routes.tracking import bp as tracking_bp

    app.register_blueprint(airports_bp)
    app.register_blueprint(passengers_bp)
    app.register_blueprint(agents_bp)
    app.register_blueprint(requests_bp)
    app.register_blueprint(dispatch_bp)
    app.register_blueprint(incidents_bp)
    app.register_blueprint(invoices_bp)
    app.register_blueprint(tracking_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(_):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(_):
        return error_response("ERR_BAD_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Bubble any non-ApiError as a 400 rather than a stack-trace 500.
        return error_response("ERR_BAD_REQUEST", str(err) or "Bad request", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
