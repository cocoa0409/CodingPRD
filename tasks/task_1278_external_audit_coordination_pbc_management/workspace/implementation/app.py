"""Entry point: Flask app, error handlers, route registration.

Boots with a completely empty in-memory store. No seeding, no preload.
"""
import os
from flask import Flask
from errors import ApiError
from response import error_response
from routes import (
    clock_routes,
    engagements,
    locations,
    pbc,
    evidence,
    queries,
    sampling,
    visits,
    adjustments,
    rep_letters,
    fee_changes,
)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(
            "ERR_NOT_FOUND", "The requested resource was not found", 404
        )

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(
            "ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405
        )

    @app.errorhandler(500)
    def handle_500(err):
        return error_response(
            "ERR_INTERNAL", "Internal server error", 500
        )

    app.register_blueprint(clock_routes.bp)
    app.register_blueprint(engagements.bp)
    app.register_blueprint(locations.bp)
    app.register_blueprint(pbc.bp)
    app.register_blueprint(evidence.bp)
    app.register_blueprint(queries.bp)
    app.register_blueprint(sampling.bp)
    app.register_blueprint(visits.bp)
    app.register_blueprint(adjustments.bp)
    app.register_blueprint(rep_letters.bp)
    app.register_blueprint(fee_changes.bp)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
