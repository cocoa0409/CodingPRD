"""HSA Investment & Administration Platform — Flask entry point.

Registers all route blueprints and the standard error handlers. The in-memory
store starts empty on every boot; NOTHING is seeded here. The logical clock
starts at its fixed default 2026-01-01T00:00:00Z.
"""
import os

from flask import Flask, request

from errors import ApiError
from middleware import caller
from response import error

from routes.reference import bp as reference_bp
from routes.accounts import bp as accounts_bp
from routes.coverage import bp as coverage_bp
from routes.contributions import bp as contributions_bp
from routes.sweeps import bp as sweeps_bp
from routes.cards import bp as cards_bp
from routes.receipts import bp as receipts_bp
from routes.distributions import bp as distributions_bp
from routes.corrections import bp as corrections_bp
from routes.tax_forms import bp as tax_forms_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

for bp in (reference_bp, accounts_bp, coverage_bp, contributions_bp, sweeps_bp,
           cards_bp, receipts_bp, distributions_bp, corrections_bp, tax_forms_bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    # Unknown route. Still enforce auth first so unauthenticated callers get 401,
    # matching the global validation ordering (PRD §2.9).
    try:
        caller()
    except ApiError as ae:
        return error(ae.error_id, ae.message, ae.http_status)
    return error("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    try:
        caller()
    except ApiError as ae:
        return error(ae.error_id, ae.message, ae.http_status)
    return error("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error(e.error_id, e.message, e.http_status)
    # Truly unexpected server-side failure. Emit an error envelope with a 500.
    return error("ERR_INTERNAL", "Unexpected error: %s" % str(e), 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
