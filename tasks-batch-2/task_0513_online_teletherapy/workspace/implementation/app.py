"""Entry point: Flask app, error handlers, blueprint registration.

In-memory storage only; the store starts empty on every boot (no seeding).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.clients import bp as clients_bp
from routes.therapists import bp as therapists_bp
from routes.matches import bp as matches_bp
from routes.live_sessions import bp as live_sessions_bp
from routes.threads import bp as threads_bp
from routes.subscriptions import bp as subscriptions_bp
from routes.resources import bp as resources_bp
from routes.crisis import bp as crisis_bp
from routes.financial_aid import bp as financial_aid_bp
from routes.superbills import bp as superbills_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clients_bp)
    app.register_blueprint(therapists_bp)
    app.register_blueprint(matches_bp)
    app.register_blueprint(live_sessions_bp)
    app.register_blueprint(threads_bp)
    app.register_blueprint(subscriptions_bp)
    app.register_blueprint(resources_bp)
    app.register_blueprint(crisis_bp)
    app.register_blueprint(financial_aid_bp)
    app.register_blueprint(superbills_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(HTTPException)
    def handle_http(e):
        # Map other HTTP exceptions (e.g. malformed JSON 400) to invalid request envelope
        code = e.code or 500
        if code == 400:
            return error_response("ERR_INVALID_REQUEST", "Bad request", 400)
        return error_response("ERR_INVALID_REQUEST", str(e), code if 400 <= code < 500 else 400)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INVALID_REQUEST", "Internal error: " + str(e), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
