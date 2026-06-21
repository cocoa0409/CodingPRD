"""Custom Tailor & Bespoke Clothing API — Flask entry point."""
import os
import socket

# Werkzeug's dev-server startup banner calls socket.getfqdn(), which can stall
# for ~5s on macOS hosts with a ".local" hostname (slow reverse-DNS lookup).
# That stall pushes per-test-server reboots toward the runner's restart timeout
# and shows up as flaky "could not be restarted" failures. gethostname() is
# instant and is all the banner needs, so pin getfqdn to it before serving.
_fast_hostname = socket.gethostname()
socket.getfqdn = lambda *args, **kwargs: _fast_hostname

from flask import Flask, jsonify

from errors import ApiError
from response import error_response

from routes.catalog import bp as catalog_bp
from routes.orders import bp as orders_bp
from routes.fittings import bp as fittings_bp
from routes.payments import bp as payments_bp
from routes.alterations import bp as alterations_bp
from routes.groups import bp as groups_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(catalog_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(fittings_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(alterations_bp)
    app.register_blueprint(groups_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        body = error_response(err.error_id, err.message)
        return jsonify(body), err.http_status

    @app.errorhandler(404)
    def handle_404(err):
        # Unknown route -> generic not-found in the standard envelope.
        body = error_response("ERR_ORDER_NOT_FOUND", "Resource not found")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(err):
        body = error_response("ERR_INVALID_REQUEST", "Method not allowed")
        return jsonify(body), 405

    @app.errorhandler(400)
    def handle_400(err):
        body = error_response("ERR_INVALID_REQUEST", "Bad request")
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Surface as a standard error envelope rather than an HTML 500.
        if isinstance(err, ApiError):
            return handle_api_error(err)
        body = error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % str(err))
        return jsonify(body), 400

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
