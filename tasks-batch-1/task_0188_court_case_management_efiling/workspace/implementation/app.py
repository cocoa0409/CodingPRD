"""Court Case Management & e-Filing API — entry point.

In-memory only; the store starts empty on every process boot. No seeding.
"""
import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

import db
from errors import ApiError
from response import error as error_response
from middleware import VALID_ROLES  # noqa: F401 (ensures module import)

from routes.courts import bp as courts_bp
from routes.cases import bp as cases_bp
from routes.parties import bp as parties_bp
from routes.filings import bp as filings_bp
from routes.service_of_process import bp as sop_bp
from routes.deadlines import bp as deadlines_bp
from routes.motions import bp as motions_bp
from routes.orders import bp as orders_bp
from routes.fee_waivers import bp as fee_waivers_bp
from routes.hearings import bp as hearings_bp
from routes.judgments import bp as judgments_bp
from routes.appeals import bp as appeals_bp


def create_app():
    app = Flask(__name__)

    for bp in (
        courts_bp, cases_bp, parties_bp, filings_bp, sop_bp, deadlines_bp,
        motions_bp, orders_bp, fee_waivers_bp, hearings_bp, judgments_bp, appeals_bp,
    ):
        app.register_blueprint(bp)

    # Serialize every request handler under a single lock so multi-resource
    # cascades and OCC checks remain consistent.
    @app.before_request
    def _acquire_lock():
        db.LOCK.acquire()
        g._held_lock = True

    @app.teardown_request
    def _release_lock(exc):
        if getattr(g, "_held_lock", False):
            try:
                db.LOCK.release()
            except RuntimeError:
                pass
            g._held_lock = False

    @app.errorhandler(ApiError)
    def _handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        if isinstance(e, HTTPException):
            code = e.code or 500
            if code == 404 or code == 405:
                return error_response("ERR_NOT_FOUND", "Resource not found", 404)
            if code == 400:
                return error_response("ERR_INVALID_REQUEST", "Bad request", 422)
            return error_response("ERR_INVALID_REQUEST", e.description or "Error", code)
        return error_response("ERR_INVALID_REQUEST", str(e), 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
