"""Cycling & Triathlon Event Operations API — Flask entry point."""
import os

from flask import Flask, jsonify

from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION
from response import error_response
from routes import clock, events, segments, waves, athletes, registrations, aid, safety, timing, penalties


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for bp in (clock.bp, events.bp, segments.bp, waves.bp, athletes.bp,
               registrations.bp, aid.bp, safety.bp, timing.bp, penalties.bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_NOT_FOUND, "method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(ERR_VALIDATION, "bad request", 400)

    @app.errorhandler(Exception)
    def handle_generic(err):
        return error_response(ERR_VALIDATION, str(err), 400)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
