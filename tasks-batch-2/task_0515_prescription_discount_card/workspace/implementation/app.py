"""Rx Discount Card API — Flask entry point.

In-memory only. No seeding. State starts empty on every boot.
"""
import os
import socket as _socket

# On some hosts (notably macOS) socket.getfqdn("0.0.0.0") blocks ~5s on a
# reverse-DNS (PTR) lookup that times out, because the unspecified address has
# no hostname. Werkzeug's dev server calls getfqdn(host) during server_bind
# purely to compose its "Running on http://..." startup log line. Under
# per-test-server isolation the server is restarted before every test, so that
# stall is paid hundreds of times and can push a boot past the restart-poll
# window, surfacing as a spurious "could not be restarted" failure. Patch the
# cosmetic lookup for unspecified addresses only; binding and request handling
# are unaffected.
_real_getfqdn = _socket.getfqdn
_UNSPECIFIED = {"", "0.0.0.0", "::", "0:0:0:0:0:0:0:0"}


def _fast_getfqdn(name=""):
    if name in _UNSPECIFIED:
        return "localhost"
    return _real_getfqdn(name)


_socket.getfqdn = _fast_getfqdn

from flask import Flask

import response
from errors import ApiError

from routes.clock import bp as clock_bp
from routes.members import bp as members_bp
from routes.drugs import bp as drugs_bp
from routes.pharmacies import bp as pharmacies_bp
from routes.price_quotes import bp as price_quotes_bp
from routes.comparisons import bp as comparisons_bp
from routes.insurance_estimates import bp as insurance_estimates_bp
from routes.discount_cards import bp as discount_cards_bp
from routes.claims import bp as claims_bp
from routes.copay_cards import bp as copay_cards_bp
from routes.copay_links import bp as copay_links_bp
from routes.gold_memberships import bp as gold_memberships_bp
from routes.mail_orders import bp as mail_orders_bp
from routes.telehealth_referrals import bp as telehealth_referrals_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(drugs_bp)
    app.register_blueprint(pharmacies_bp)
    app.register_blueprint(price_quotes_bp)
    app.register_blueprint(comparisons_bp)
    app.register_blueprint(insurance_estimates_bp)
    app.register_blueprint(discount_cards_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(copay_cards_bp)
    app.register_blueprint(copay_links_bp)
    app.register_blueprint(gold_memberships_bp)
    app.register_blueprint(mail_orders_bp)
    app.register_blueprint(telehealth_referrals_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return response.error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_err):
        return response.error_response("ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(_err):
        return response.error_response("ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(400)
    def handle_400(_err):
        return response.error_response("ERR_INVALID_REQUEST", "Malformed request.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return response.error_response(err.error_id, err.message, err.http_status)
        return response.error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % err, 400)

    return app


app = create_app()


if __name__ == "__main__":
    import time
    port = int(os.environ.get("PORT", "10000"))
    # Under per-test-server isolation the runner SIGKILLs the previous server and
    # immediately spawns this one on the same port. The kernel can hold the port
    # for a brief moment after the predecessor dies, so a single bind() attempt
    # may raise "Address already in use" and exit instantly — which the runner
    # reports as "could not be restarted". Retry the bind a few times so a
    # transient port hand-off doesn't crash the boot under the concurrent sweep.
    last_err = None
    for _attempt in range(40):
        try:
            app.run(host="0.0.0.0", port=port, threaded=True)
            break
        except OSError as e:  # e.g. EADDRINUSE while predecessor's socket drains
            last_err = e
            time.sleep(0.25)
    else:
        raise SystemExit("Could not bind port %d: %s" % (port, last_err))
