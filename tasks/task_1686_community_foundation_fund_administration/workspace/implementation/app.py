"""Community Foundation Funds API — Flask entrypoint."""
import os

from flask import Flask, jsonify

from common import ApiError, error_body
import routes_core
import routes_gifts
import routes_invest
import routes_grants
import routes_finance
import routes_scholarship


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (
        routes_core, routes_gifts, routes_invest,
        routes_grants, routes_finance, routes_scholarship,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return jsonify(error_body(e)), e.status

    @app.errorhandler(404)
    def handle_404(e):
        return jsonify(error_body(ApiError(
            "ERR_NOT_FOUND", 404, "Resource not found"))), 404

    @app.errorhandler(405)
    def handle_405(e):
        return jsonify(error_body(ApiError(
            "ERR_NOT_FOUND", 404, "Resource not found"))), 404

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return jsonify(error_body(e)), e.status
        return jsonify(error_body(ApiError(
            "ERR_FIELD_CONSTRAINT", 422, f"Malformed request: {e}"))), 422

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
