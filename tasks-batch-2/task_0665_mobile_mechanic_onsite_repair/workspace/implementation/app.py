"""Mobile Mechanic & On-Site Auto Repair API — Flask entry point.

In-memory only. No persistence. No entity seeding at startup.
"""
import os

from flask import Flask, jsonify

import response
from errors import ApiError
from routes.seeding import bp as seeding_bp
from routes.service_requests import bp as service_requests_bp
from routes.quotes import bp as quotes_bp
from routes.collections import bp as collections_bp
from routes.job_visits import bp as job_visits_bp
from routes.payments import bp as payments_bp
from routes.warranty_claims import bp as warranty_claims_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(seeding_bp)
    app.register_blueprint(service_requests_bp)
    app.register_blueprint(quotes_bp)
    app.register_blueprint(collections_bp)
    app.register_blueprint(job_visits_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(warranty_claims_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_e):
        return response.error("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(_e):
        return response.error("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return response.error(err.error_id, err.message, err.http_status)
        return response.error("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
