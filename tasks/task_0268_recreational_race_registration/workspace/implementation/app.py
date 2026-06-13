"""Recreational Race Registration API — Flask entry point.

In-memory storage only; the store starts EMPTY on every boot (no seeding).
Reads $PORT (default 10000), binds 0.0.0.0, runs in the foreground.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

from routes.participants import bp as participants_bp
from routes.events import bp as events_bp
from routes.distances import bp as distances_bp
from routes.registrations import bp as registrations_bp
from routes.waitlist import bp as waitlist_bp
from routes.pledges import bp as pledges_bp
from routes.transfers import bp as transfers_bp
from routes.packets import bp as packets_bp
from routes.bibs import bp as bibs_bp
from routes.results import bp as results_bp


def create_app():
    app = Flask(__name__)

    app.register_blueprint(participants_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(distances_bp)
    app.register_blueprint(registrations_bp)
    app.register_blueprint(waitlist_bp)
    app.register_blueprint(pledges_bp)
    app.register_blueprint(transfers_bp)
    app.register_blueprint(packets_bp)
    app.register_blueprint(bibs_bp)
    app.register_blueprint(results_bp)

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
        # Map unexpected werkzeug HTTP errors (e.g. malformed JSON -> 400)
        # to the request-validation error so the envelope stays consistent.
        if e.code == 400:
            return error_response("ERR_INVALID_REQUEST", "Bad request", 422)
        return error_response("ERR_INVALID_REQUEST", str(e), e.code or 422)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
