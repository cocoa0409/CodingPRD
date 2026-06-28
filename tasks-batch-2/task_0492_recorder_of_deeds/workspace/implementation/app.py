"""Recorder of Deeds / County Land Recording API — Flask entry point.

In-memory store, logical clock, NO entity seeding at startup. start.sh launches
this in the foreground binding 0.0.0.0:$PORT (default 10000). The store starts
empty on every boot; tests build all preconditions via the declared API."""
import os

from flask import Flask

import errors
from response import error_response

from routes.clock_routes import bp as clock_bp
from routes.offices import bp as offices_bp
from routes.submitters import bp as submitters_bp
from routes.packages import bp as packages_bp
from routes.recorded_documents import bp as recorded_documents_bp
from routes.plats import bp as plats_bp
from routes.ucc_filings import bp as ucc_filings_bp
from routes.copy_search import bp as copy_search_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(offices_bp)
    app.register_blueprint(submitters_bp)
    app.register_blueprint(packages_bp)
    app.register_blueprint(recorded_documents_bp)
    app.register_blueprint(plats_bp)
    app.register_blueprint(ucc_filings_bp)
    app.register_blueprint(copy_search_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(errors.ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        # Unknown method on a known path -> treat as not found per the contract.
        return error_response(errors.ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(400)
    def handle_400(e):
        return error_response(errors.ERR_INVALID_REQUEST, 422, "Bad request")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, errors.ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response(errors.ERR_INVALID_REQUEST, 422, str(e))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
