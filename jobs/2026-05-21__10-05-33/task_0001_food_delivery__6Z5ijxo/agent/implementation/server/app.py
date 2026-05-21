from flask import Flask, g, request
from .clock import LogicalClock
from .errors import APIError, err
from .envelope import error_response, success
from .ids import new_request_id


logical_clock = LogicalClock()


def create_app() -> Flask:
    app = Flask(__name__)

    @app.before_request
    def assign_request_id():
        g.request_id = new_request_id()

    @app.errorhandler(APIError)
    def handle_api_error(e: APIError):
        return error_response(e)

    @app.errorhandler(404)
    def handle_not_found(_):
        return error_response(err("ERR_NOT_FOUND", "Endpoint not found"))

    @app.errorhandler(405)
    def handle_405(_):
        return error_response(err("ERR_NOT_FOUND", "Method not allowed"))

    @app.errorhandler(400)
    def handle_400(_):
        return error_response(err("ERR_VALIDATION", "Bad request"))

    @app.errorhandler(Exception)
    def handle_uncaught(e):
        app.logger.exception("Unhandled exception: %s", e)
        return error_response(err("ERR_VALIDATION", "Internal error"))

    from .routes import register_routes
    register_routes(app)

    @app.route("/health")
    def health():
        return success({"status": "ok"})

    return app
