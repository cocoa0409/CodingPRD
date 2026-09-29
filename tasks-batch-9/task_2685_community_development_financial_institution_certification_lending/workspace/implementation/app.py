"""CDFI Certification & Lending API -- Flask entry point.

Storage is in-memory only and starts empty on every boot: no entity is seeded,
preloaded or hardcoded here.  Every resource is created by clients through the
endpoints declared in PRD 4.
"""
import os
import sys
import traceback

from flask import Flask, jsonify

from envelope import error_body
from errors import ApiError
from routes import awards, borrowers, certification, governance, impact
from routes import institutions, loans, measurements

API_PREFIX = "/cdfi"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False
    for module in (institutions, governance, certification, borrowers, loans,
                   impact, measurements, awards):
        app.register_blueprint(module.bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def handle_not_found(exc):
        return jsonify(error_body(
            "ERR_INVALID_REQUEST", "No route matches the requested path.")), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return jsonify(error_body(
            "ERR_INVALID_REQUEST", "Method not allowed for this path.")), 405

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        traceback.print_exc(file=sys.stderr)
        return jsonify(error_body("ERR_INVALID_REQUEST", str(exc))), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True, debug=False, use_reloader=False)
