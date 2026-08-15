"""FAFSA Completion Campaign API — Flask entry point."""

import os

from flask import Flask, jsonify

import errors as err
from response import error_response
from routes import campaigns, seniors, events, cases


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(campaigns.bp)
    app.register_blueprint(seniors.bp)
    app.register_blueprint(events.bp)
    app.register_blueprint(cases.bp)

    @app.errorhandler(err.ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(err.ERR_INVALID_REQUEST, 404, "Route not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(err.ERR_INVALID_REQUEST, 405, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_exception(e):
        if isinstance(e, err.ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response(err.ERR_INVALID_REQUEST, 500, f"Internal error: {e}")

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
