"""Broadband Consumer Label Compliance API — Flask application entry point.

Storage is in-memory only and starts completely empty on every boot; the
logical clock starts at exactly 2026-08-01T00:00:00Z (PRD §2.4).
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
import response
from routes import (accounts, clock, complaints, labels, measurement, notices,
                    regulator, service_plans)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock.bp)
    app.register_blueprint(service_plans.bp)
    app.register_blueprint(measurement.bp)
    app.register_blueprint(labels.bp)
    app.register_blueprint(accounts.bp)
    app.register_blueprint(complaints.bp)
    app.register_blueprint(regulator.bp)
    app.register_blueprint(notices.bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(error):
        return response.failure(error.error_id, error.message,
                                error.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        return response.failure(errors.ERR_INVALID_REQUEST,
                                error.description or "The request could not be "
                                "processed.",
                                error.code or 400)

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):  # pragma: no cover
        return response.failure("ERR_INTERNAL", str(error) or "Internal error.",
                                500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False,
            use_reloader=False)
