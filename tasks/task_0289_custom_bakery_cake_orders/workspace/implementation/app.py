"""Custom Bakery & Cake Orders API — Flask entry point.

In-memory store only; no seeding. Boots clean on every process start.
"""
import os

from flask import Flask, jsonify

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_response
from routes.config import bp as config_bp
from routes.orders import bp as orders_bp
from routes.proofs import bp as proofs_bp
from routes.payments import bp as payments_bp
from routes.slots import bp as slots_bp
from routes.production import bp as production_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(config_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(proofs_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(slots_bp)
    app.register_blueprint(production_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        body = error_response(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def handle_404(exc):
        body = error_response(ERR_NOT_FOUND[0], "resource not found")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(exc):
        body = error_response(ERR_NOT_FOUND[0], "method not allowed")
        return jsonify(body), 405

    @app.errorhandler(400)
    def handle_400(exc):
        body = error_response(ERR_INVALID_REQUEST[0], "bad request")
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return handle_api_error(exc)
        body = error_response(ERR_INVALID_REQUEST[0], f"internal error: {exc}")
        return jsonify(body), 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Serve via waitress (a production WSGI server) when available: it boots
    # fast and keeps HTTP connections robust under heavy host CPU contention,
    # where the Werkzeug dev server can drop connections (BadStatusLine) or
    # miss the harness restart-readiness window. Routes/responses are identical
    # either way. Fall back to the dev server if waitress is not installed.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8, _quiet=True)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
