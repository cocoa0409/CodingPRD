"""Entry point: Flask app, error handlers, route registration.

Storage is fully in-memory (see db.py). A fresh process boot starts with an
empty store and the logical clock at exactly 2026-08-01T00:00:00Z. Nothing is
seeded.
"""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

from routes import (
    ops, stores, employees, events, alerts, cases, interviews, evidence,
    demands, payments, orc, shrink_periods, referral_packets,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(ops.bp)
    app.register_blueprint(stores.bp)
    app.register_blueprint(employees.bp)
    app.register_blueprint(events.bp)
    app.register_blueprint(alerts.bp)
    app.register_blueprint(cases.bp)
    app.register_blueprint(interviews.bp)
    app.register_blueprint(evidence.bp)
    app.register_blueprint(demands.bp)
    app.register_blueprint(payments.bp)
    app.register_blueprint(orc.bp)
    app.register_blueprint(shrink_periods.bp)
    app.register_blueprint(referral_packets.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ApiError(ERR_NOT_FOUND, "Resource not found", 404))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(
            ApiError(ERR_INVALID_REQUEST, "Method not allowed", 400))

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(
            ApiError(ERR_INVALID_REQUEST, "Malformed request", 400))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err)
        import traceback
        traceback.print_exc()
        return error_response(
            ApiError(ERR_INVALID_REQUEST, "Unexpected error: %s" % err, 400))

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
