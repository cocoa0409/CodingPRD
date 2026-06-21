"""Pet Boarding, Daycare & Kennel API — Flask entry point.

In-memory storage only; fresh empty state on every boot. No seeding.
"""
import os

from flask import Flask

import errors
import response
from routes.facilities import bp as facilities_bp
from routes.owners import bp as owners_bp
from routes.pets import bp as pets_bp
from routes.runs import bp as runs_bp
from routes.reservations import bp as reservations_bp
from routes.packages import bp as packages_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(facilities_bp)
    app.register_blueprint(owners_bp)
    app.register_blueprint(pets_bp)
    app.register_blueprint(runs_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(packages_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return response.error(e)

    @app.errorhandler(404)
    def handle_404(e):
        return response.error(errors.err_not_found())

    @app.errorhandler(405)
    def handle_405(e):
        # Method not allowed on a known path -> treat as forbidden-style 404
        # is not appropriate; surface as not found of the route.
        return response.error(errors.err_not_found())

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, errors.ApiError):
            return response.error(e)
        # Surface unexpected errors as a generic 500-style envelope.
        err = errors.ApiError("ERR_INTERNAL", 500, str(e))
        return response.error(err)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
