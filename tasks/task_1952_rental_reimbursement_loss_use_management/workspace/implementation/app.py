"""Rental Reimbursement & Loss-of-Use Management API — entry point."""
import os

from flask import Flask

import db
import routes_admin
import routes_claims
import routes_class_changes
import routes_extensions
import routes_invoices
import routes_lou
import routes_recovery
import routes_repair
import routes_reservations
import routes_verifications
from errors import ApiError
from response import error_response, ok

app = Flask(__name__)

for module in (routes_admin, routes_claims, routes_verifications, routes_repair,
               routes_reservations, routes_extensions, routes_class_changes,
               routes_lou, routes_invoices, routes_recovery):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


class _LockedMiddleware:
    """Serialize requests through one process-wide lock."""

    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        with db.lock:
            return self.wsgi_app(environ, start_response)


app.wsgi_app = _LockedMiddleware(app.wsgi_app)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
