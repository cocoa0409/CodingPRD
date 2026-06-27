"""ATM Cash Logistics API — Flask entry point.

Registers all route blueprints and the global error handlers that render the
standard error envelope. Storage is in-memory only (see db.py); the store is
empty on every boot — no seeding.

Boots in the foreground on 0.0.0.0:$PORT (default 10000).
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from db import store
from errors import ApiError
from response import error_response
from routes.admin import bp as admin_bp
from routes.atms import bp as atms_bp
from routes.config import bp as config_bp
from routes.disclosures import bp as disclosures_bp
from routes.replenishment import bp as replenishment_bp
from routes.settlement import bp as settlement_bp
from routes.tickets import bp as tickets_bp
from routes.transactions import bp as transactions_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(config_bp)
app.register_blueprint(atms_bp)
app.register_blueprint(replenishment_bp)
app.register_blueprint(transactions_bp)
app.register_blueprint(tickets_bp)
app.register_blueprint(disclosures_bp)
app.register_blueprint(settlement_bp)
app.register_blueprint(admin_bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(store.clock, exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(exc):
    # Unknown route — render a not-found in the standard envelope.
    return error_response(store.clock, "ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(exc):
    return error_response(store.clock, "ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    # Generic fallback for other werkzeug HTTP errors (e.g. malformed body).
    status = exc.code or 500
    if status == 400:
        return error_response(store.clock, "ERR_INVALID_REQUEST", "Bad request.", 422)
    return error_response(store.clock, "ERR_INVALID_REQUEST", str(exc), status)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    # Last-resort guard so the server never leaks a non-enveloped 500.
    return error_response(store.clock, "ERR_INVALID_REQUEST", "Internal error.", 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Prefer waitress: a robust pure-Python WSGI server that handles the
    # connection backlog cleanly (the test harness fires a setup sequence of
    # many short-lived requests per server lifetime). Fall back to Flask's dev
    # server only if waitress is unavailable.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
