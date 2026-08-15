"""Entry point: Flask app, error handlers, route registration.

Storage is in-memory only (module-level dicts in db.py). The store starts
empty on every boot — nothing is seeded. Re-invoking start.sh therefore wipes
all state, guaranteeing a fresh boot for per-test-server isolation.
"""

import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST
from response import error as error_response

from routes import jurisdictions, reviewers, engagements, cycles, assignments
from routes import comments, deferred, records, clock


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(jurisdictions.bp)
    app.register_blueprint(reviewers.bp)
    app.register_blueprint(engagements.bp)
    app.register_blueprint(cycles.bp)
    app.register_blueprint(assignments.bp)
    app.register_blueprint(comments.bp)
    app.register_blueprint(deferred.bp)
    app.register_blueprint(records.bp)
    app.register_blueprint(clock.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_INVALID_REQUEST, "Route not found", 400)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_INVALID_REQUEST, "Method not allowed", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response(ERR_INVALID_REQUEST, "Internal error: %s" % err, 400)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
