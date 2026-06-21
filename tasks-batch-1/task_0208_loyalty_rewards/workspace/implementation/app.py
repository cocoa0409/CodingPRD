"""Loyalty Rewards API entry point.

Registers all route blueprints, installs the standard error envelope handlers,
and runs the Flask server in the foreground bound to 0.0.0.0:$PORT.

Storage is in-memory only (see db.py). No seeding, no disk, no external state —
a fresh process starts with empty collections every time.
"""
import os
import socket as _socket

# --- Fast-boot guard (behavior-neutral) -----------------------------------
# On macOS, socket.getfqdn("0.0.0.0") blocks ~5s on a reverse-DNS (PTR) lookup
# that times out, because the unspecified address has no hostname. Werkzeug's
# dev server calls getfqdn(host) during server_bind purely to compose its
# "Running on http://..." startup log line. Under per-test-server isolation the
# server is rebooted before every test, so that 5s stall is paid hundreds of
# times and, under the concurrent stability sweep, can push a boot past the
# restart-poll window and surface as a spurious "could not be restarted".
#
# The runner normally injects an equivalent sitecustomize patch via PYTHONPATH,
# but we replicate it here so the server boots fast regardless of how it is
# launched. This only changes the cosmetic startup log-line hostname for the
# unspecified-address cases; getfqdn's result is never used for anything else,
# the server still binds 0.0.0.0 and serves identical responses, and named
# addresses fall through to the real resolver unchanged. No API or test
# behavior is affected.
_real_getfqdn = _socket.getfqdn
_UNSPECIFIED_HOSTS = {"", "0.0.0.0", "::", "0:0:0:0:0:0:0:0"}


def _fast_getfqdn(name=""):
    if name in _UNSPECIFIED_HOSTS:
        return "localhost"
    return _real_getfqdn(name)


_socket.getfqdn = _fast_getfqdn
# --------------------------------------------------------------------------

from flask import Flask

from errors import ApiError
from response import error_response
from routes.programs import bp as programs_bp
from routes.members import bp as members_bp
from routes.purchases import bp as purchases_bp
from routes.redemptions import bp as redemptions_bp
from routes.referrals import bp as referrals_bp
from routes.transfers import bp as transfers_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(programs_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(purchases_bp)
    app.register_blueprint(redemptions_bp)
    app.register_blueprint(referrals_bp)
    app.register_blueprint(transfers_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Surface unexpected errors in the standard envelope rather than HTML.
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_INVALID_REQUEST", str(e), 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
