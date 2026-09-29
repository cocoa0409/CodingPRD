"""Vegetation Line Clearance API - application entry point."""
import os

from flask import Flask, jsonify

import envelope
from errors import ApiError
from routes import (billing, circuits, clock, crews, hazard, notifications, permits,
                    prescriptions, production, storms, workorders, workplans)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for module in (prescriptions, circuits, workplans, workorders, crews, production,
                   notifications, hazard, permits, storms, billing, clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return envelope.error_response(err)

    @app.errorhandler(404)
    def handle_404(_err):
        return envelope.error_response(
            ApiError("ERR_VALIDATION", "no route matches the request path", 404))

    @app.errorhandler(405)
    def handle_405(_err):
        return envelope.error_response(
            ApiError("ERR_VALIDATION", "method not allowed", 405))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return envelope.error_response(err)
        return jsonify({
            "meta": {"api_request_id": "req_INTERNAL", "api_request_timestamp": ""},
            "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": str(err)},
        }), 500

    @app.get("/health")
    def health():
        return jsonify({"status": "ok"}), 200

    return app


application = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    application.run(host="0.0.0.0", port=port, threaded=True)
