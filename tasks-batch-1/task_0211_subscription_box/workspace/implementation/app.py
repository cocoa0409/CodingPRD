"""Subscription Box API — Flask entry point.

In-memory only; the store starts empty on every boot (per-test-server isolation).
No seeding, preloading, or hardcoded entity data at startup.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response

# Blueprints (one per resource group)
from routes.plans import bp as plans_bp
from routes.products import bp as products_bp
from routes.subscribers import bp as subscribers_bp
from routes.subscriptions import bp as subscriptions_bp
from routes.box_selections import bp as box_selections_bp
from routes.waves import bp as waves_bp
from routes.allocations import bp as allocations_bp
from routes.shipments import bp as shipments_bp
from routes.billing import bp as billing_bp
from routes.gifts import bp as gifts_bp
from routes.admin import bp as admin_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(plans_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(subscribers_bp)
    app.register_blueprint(subscriptions_bp)
    app.register_blueprint(box_selections_bp)
    app.register_blueprint(waves_bp)
    app.register_blueprint(allocations_bp)
    app.register_blueprint(shipments_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(gifts_bp)
    app.register_blueprint(admin_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Malformed request.", 400)

    @app.errorhandler(Exception)
    def handle_uncaught(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))

    # Boot-latency guard. Python's http.server.server_bind() calls
    # socket.getfqdn(host) to populate the cosmetic server_name attribute. On
    # hosts whose ".local" hostname is not reverse-resolvable, getfqdn() blocks
    # ~5s on a DNS timeout *before* the accept loop starts. Under per-test-server
    # isolation (server rebooted before every test, 8 rounds concurrent) that
    # stall can push a boot past the runner's restart window and flake as
    # "could not be restarted". server_name is never consulted during request
    # handling, so stubbing getfqdn to skip the lookup changes no API behavior.
    import socket

    _real_getfqdn = socket.getfqdn

    def _fast_getfqdn(name=""):
        if name in ("", "0.0.0.0", "::"):
            return name or "0.0.0.0"
        return name

    socket.getfqdn = _fast_getfqdn

    # Serve via Werkzeug's make_server + serve_forever (instead of app.run(),
    # which additionally calls log_startup() → get_interface_ip() → another slow
    # hostname resolution). Serving behavior is otherwise identical.
    from werkzeug.serving import make_server

    srv = make_server("0.0.0.0", port, app, threaded=True)
    srv.serve_forever()
