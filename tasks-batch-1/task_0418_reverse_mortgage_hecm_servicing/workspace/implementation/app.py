"""HECM servicing API — entry point, error handlers, route registration."""
import os
import socket

# On macOS the default `.local` hostname resolves via mDNS, and a failed
# lookup blocks for ~5 seconds. Python's http.server.HTTPServer.server_bind()
# (werkzeug's dev server inherits it) calls socket.getfqdn(host) at bind time,
# so every per-test-server reboot would otherwise stall ~5s before the port
# opens — under the 8-round concurrent sweep that blows past the runner's boot
# timeout and turns every test into an ERROR. Pin getfqdn to a fast, lookup-free
# answer so the server binds immediately. This only affects the cosmetic
# server_name; it does not change any request/response behaviour.
_orig_getfqdn = socket.getfqdn


def _fast_getfqdn(name=""):
    try:
        return name or socket.gethostname()
    except Exception:
        return "localhost"


socket.getfqdn = _fast_getfqdn

from flask import Flask

import errors
from response import error_response

from routes.lenders import bp as lenders_bp
from routes.plf import bp as plf_bp
from routes.borrowers import bp as borrowers_bp
from routes.loans import bp as loans_bp
from routes.disbursements import bp as disbursements_bp
from routes.lesa import bp as lesa_bp
from routes.property_charges import bp as property_charges_bp
from routes.occupancy import bp as occupancy_bp
from routes.maturity import bp as maturity_bp
from routes.deferrals import bp as deferrals_bp
from routes.resolutions import bp as resolutions_bp
from routes.ledger_entries import bp as ledger_entries_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(lenders_bp)
    app.register_blueprint(plf_bp)
    app.register_blueprint(borrowers_bp)
    app.register_blueprint(loans_bp)
    app.register_blueprint(disbursements_bp)
    app.register_blueprint(lesa_bp)
    app.register_blueprint(property_charges_bp)
    app.register_blueprint(occupancy_bp)
    app.register_blueprint(maturity_bp)
    app.register_blueprint(deferrals_bp)
    app.register_blueprint(resolutions_bp)
    app.register_blueprint(ledger_entries_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(errors.ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(errors.ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, errors.ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response(errors.ERR_INVALID_REQUEST, 400, "Unexpected error: %s" % e)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
