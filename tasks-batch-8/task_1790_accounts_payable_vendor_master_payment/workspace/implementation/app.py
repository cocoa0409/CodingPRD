"""AP Vendor Master & Payment Controls API — entry point.

Boots a Flask server bound to 0.0.0.0:$PORT (default 10000) in the foreground.
All state is in-memory (see db.py); nothing is seeded at startup and nothing
is persisted to disk, so every fresh process boots a completely empty system.
"""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from response import error_response
import routes_ops
import routes_vendors
import routes_bank
import routes_compliance
import routes_matrix
import routes_invoices
import routes_payments
import routes_audit

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (
    routes_ops,
    routes_vendors,
    routes_bank,
    routes_compliance,
    routes_matrix,
    routes_invoices,
    routes_payments,
    routes_audit,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_not_found(err):
    return error_response(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Resource not found.")


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return error_response(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Resource not found.")


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response("ERR_INTERNAL", 500, "Unexpected server error: %s" % err)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
