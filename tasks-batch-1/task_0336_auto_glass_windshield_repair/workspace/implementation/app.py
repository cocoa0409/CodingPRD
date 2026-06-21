"""Auto Glass & Windshield Repair API — Flask entry point.

In-memory store only; no seeding at startup. Boots clean on every invocation.
"""
import os
import socket

# --- Fast-boot guard -------------------------------------------------------
# On some hosts socket.getfqdn()/gethostbyname() block ~5s on a reverse-DNS
# timeout. Werkzeug's dev server resolves the host while building its startup
# banner, so the server does not accept connections until that lookup returns.
# Under per-test-server isolation the server is rebooted before every test, so
# a 5s DNS stall on each boot blows the runner's startup window and surfaces as
# mass "could not be restarted"/timeout errors. Short-circuit the lookups so
# the server is ready within milliseconds. No DNS is needed: tests connect to
# 127.0.0.1 and the app binds 0.0.0.0 directly.
_HOSTNAME = socket.gethostname()
socket.getfqdn = lambda name="": _HOSTNAME  # type: ignore[assignment]
_orig_gethostbyname = socket.gethostbyname


def _fast_gethostbyname(name):
    if name in ("", _HOSTNAME, "localhost"):
        return "127.0.0.1"
    try:
        return _orig_gethostbyname(name)
    except OSError:
        return "127.0.0.1"


socket.gethostbyname = _fast_gethostbyname  # type: ignore[assignment]

from flask import Flask
from werkzeug.exceptions import HTTPException

import errors
import response
from errors import ApiError
from routes.appointments import bp as appointments_bp
from routes.catalog import bp as catalog_bp
from routes.customers import bp as customers_bp
from routes.part_orders import bp as part_orders_bp
from routes.payments import bp as payments_bp
from routes.recalibration import bp as recalibration_bp
from routes.warranties import bp as warranties_bp
from routes.work_orders import bp as work_orders_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(customers_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(work_orders_bp)
    app.register_blueprint(part_orders_bp)
    app.register_blueprint(appointments_bp)
    app.register_blueprint(recalibration_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(warranties_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.http_status, exc.message)

    @app.errorhandler(404)
    def handle_404(exc):
        # Unmatched route -> generic invalid request (no entity context).
        return response.error(errors.ERR_INVALID_REQUEST, 404, "Resource not found.")

    @app.errorhandler(405)
    def handle_405(exc):
        return response.error(errors.ERR_INVALID_REQUEST, 405, "Method not allowed.")

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc):
        return response.error(errors.ERR_INVALID_REQUEST, exc.code or 500, exc.description)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error("ERR_INTERNAL", 500, str(exc))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
