"""Property Tax Assessment & Appeal API — Flask entry point.

In-memory store only (db.py). The store starts EMPTY on every boot; no entity
is ever seeded. start.sh re-invocation (per-test-server isolation) restarts the
process and re-initialises all module-level dicts empty, wiping state.
"""
import os

from flask import Flask

from errors import ApiError, ERROR_STATUS
from response import error_response

from routes.owners import bp as owners_bp
from routes.tax_rolls import bp as tax_rolls_bp
from routes.parcels import bp as parcels_bp
from routes.assessments import bp as assessments_bp
from routes.exemptions import bp as exemptions_bp
from routes.appeals import bp as appeals_bp
from routes.hearings import bp as hearings_bp
from routes.tax_bills import bp as tax_bills_bp
from routes.deferrals import bp as deferrals_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (owners_bp, tax_rolls_bp, parcels_bp, assessments_bp,
               exemptions_bp, appeals_bp, hearings_bp, tax_bills_bp,
               deferrals_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(_e):
        # Unknown route / path id not matched -> ERR_NOT_FOUND envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found",
                              ERROR_STATUS["ERR_NOT_FOUND"])

    @app.errorhandler(405)
    def handle_405(_e):
        return error_response("ERR_NOT_FOUND", "Method not allowed",
                              ERROR_STATUS["ERR_NOT_FOUND"])

    @app.errorhandler(400)
    def handle_400(_e):
        return error_response("ERR_INVALID_REQUEST", "Malformed request",
                              ERROR_STATUS["ERR_INVALID_REQUEST"])

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error", 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
