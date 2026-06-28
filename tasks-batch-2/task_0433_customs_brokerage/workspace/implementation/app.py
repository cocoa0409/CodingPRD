"""Customs Brokerage & Import Compliance API — entry point.

Registers all routes, installs error handlers, and boots a Flask server.
Storage is entirely in-memory (see db.py) and starts EMPTY on every process
start — no seeding, no preload, no persistence.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response

# Route blueprints
from routes.importers import bp as importers_bp
from routes.bonds import bp as bonds_bp
from routes.isf_filings import bp as isf_bp
from routes.entries import bp as entries_bp
from routes.pga_reviews import bp as pga_bp
from routes.exam_slots import bp as exam_bp
from routes.monthly_statements import bp as statements_bp
from routes.post_summary_corrections import bp as psc_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        importers_bp, bonds_bp, isf_bp, entries_bp, pga_bp, exam_bp,
        statements_bp, psc_bp, clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        body = error_response(exc.error_id, exc.message)
        resp = jsonify(body)
        resp.status_code = exc.http_status
        return resp

    @app.errorhandler(404)
    def handle_404(_exc):
        body = error_response("ERR_NOT_FOUND", "Resource not found.")
        resp = jsonify(body)
        resp.status_code = 404
        return resp

    @app.errorhandler(405)
    def handle_405(_exc):
        body = error_response("ERR_NOT_FOUND", "Method not allowed.")
        resp = jsonify(body)
        resp.status_code = 404
        return resp

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        body = error_response("ERR_VALIDATION", "Unexpected error: %s" % exc)
        resp = jsonify(body)
        resp.status_code = 422
        return resp

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
