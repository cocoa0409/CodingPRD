"""Prior Learning Assessment & Credit for Experience API.

All state lives in process memory (see db.py) and vanishes when the process
exits. Nothing is seeded at startup: every entity is created through the API.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_body
from routes.appeals import bp as appeals_bp
from routes.articulation import bp as articulation_bp
from routes.assignments import bp as assignments_bp
from routes.catalog import bp as catalog_bp
from routes.claims import bp as claims_bp
from routes.invoices import bp as invoices_bp
from routes.people import bp as people_bp
from routes.portfolios import bp as portfolios_bp
from routes.system import bp as system_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in (catalog_bp, articulation_bp, people_bp, claims_bp,
                      portfolios_bp, assignments_bp, invoices_bp, appeals_bp,
                      system_bp):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def handle_404(exc):
        return jsonify(error_body("ERR_NOT_FOUND", "Resource not found")), 404

    @app.errorhandler(405)
    def handle_405(exc):
        return jsonify(error_body("ERR_NOT_FOUND", "Method not allowed for this path")), 404

    @app.errorhandler(400)
    def handle_400(exc):
        return jsonify(error_body("ERR_INVALID_REQUEST", "Malformed request")), 400

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        app.logger.exception("unhandled error")
        return jsonify(error_body("ERR_INVALID_REQUEST", str(exc))), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
