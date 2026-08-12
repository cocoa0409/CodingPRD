"""Charter School Authorizing API — Flask entry point.

Mounts every route declared in SCAFFOLD.yaml §1.5 and wires the standard
error envelope (§2.2). Storage is purely in-memory (db.py) and starts empty
on every boot — no seeding, no persistence.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import (
    appeals,
    applications,
    clock_routes,
    closures,
    contracts,
    fees,
    interventions,
    lotteries,
    monitoring,
    renewals,
    schools,
)


def create_app() -> Flask:
    app = Flask(__name__)

    app.register_blueprint(clock_routes.bp)
    app.register_blueprint(applications.bp)
    app.register_blueprint(applications.bp_interviews)
    app.register_blueprint(schools.bp)
    app.register_blueprint(contracts.bp)
    app.register_blueprint(monitoring.bp)
    app.register_blueprint(lotteries.bp)
    app.register_blueprint(interventions.bp)
    app.register_blueprint(renewals.bp)
    app.register_blueprint(closures.bp)
    app.register_blueprint(fees.bp)
    app.register_blueprint(appeals.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.http_status, err.message)

    @app.errorhandler(404)
    def handle_not_found(_err):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        # Never leak a stack trace through the envelope.
        return error_response("ERR_INVALID_REQUEST", 400, str(err) or "Unexpected error")

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
