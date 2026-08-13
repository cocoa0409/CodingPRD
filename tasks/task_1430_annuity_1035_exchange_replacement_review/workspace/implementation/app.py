"""Flask application entry point.

The store starts empty on every boot — no entity seeding at startup.
"""
import os
import sys

# Make sibling packages importable when running as `python3 app.py`
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify

import db
from errors import ApiError
from response import error_response
from routes import clock, producers, clients, contracts, cases, documents, transfers


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # Register blueprints
    app.register_blueprint(clock.bp)
    app.register_blueprint(producers.bp)
    app.register_blueprint(clients.bp)
    app.register_blueprint(contracts.bp)
    app.register_blueprint(cases.bp)
    app.register_blueprint(documents.bp)
    app.register_blueprint(transfers.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(
            "ERR_NOT_FOUND",
            "The requested resource was not found",
            404,
        )

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(
            "ERR_NOT_FOUND",
            "The requested resource was not found",
            404,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Never leak a stack trace; surface a 500 with a generic error id.
        import traceback
        traceback.print_exc()
        return error_response(
            "ERR_INTERNAL",
            f"Internal server error: {err}",
            500,
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
