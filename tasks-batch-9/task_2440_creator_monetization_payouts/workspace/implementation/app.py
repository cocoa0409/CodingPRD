"""Creator Monetization Payouts API — entry point.

Storage is in-memory only and starts completely empty on every boot: no entity
is seeded, preloaded or hardcoded here or in any imported module.
"""
import os

from flask import Flask, jsonify

from apierrors import ApiError
from envelope import error_body
from routes import blueprints


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    for blueprint in blueprints:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(404)
    def _not_found(_exc):
        return jsonify(error_body("ERR_NOT_FOUND", "Unknown route.")), 404

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return jsonify(error_body("ERR_METHOD_NOT_ALLOWED", "Method not allowed.")), 405

    @app.errorhandler(Exception)
    def _unhandled(exc):  # pragma: no cover - defensive
        if isinstance(exc, ApiError):
            return _api_error(exc)
        return jsonify(error_body("ERR_INVALID_FIELD_VALUE", str(exc))), 422

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
