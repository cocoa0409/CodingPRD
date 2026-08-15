"""Digital Ad Campaign Trafficking API — entry point."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from core import ApiError, envelope_error

app = Flask(__name__)

import routes_io
import routes_line_items
import routes_creatives
import routes_delivery
import routes_verify
import routes_billing

app.register_blueprint(routes_io.bp)
app.register_blueprint(routes_line_items.bp)
app.register_blueprint(routes_creatives.bp)
app.register_blueprint(routes_delivery.bp)
app.register_blueprint(routes_verify.bp)
app.register_blueprint(routes_billing.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return envelope_error(e.error_id, e.message, e.status)


@app.errorhandler(HTTPException)
def handle_http_error(e):
    if e.code == 404:
        return envelope_error("ERR_NOT_FOUND", "Resource not found", 404)
    if e.code == 405:
        return envelope_error("ERR_INVALID_REQUEST", "Method not allowed", 405)
    if e.code == 400:
        return envelope_error("ERR_INVALID_REQUEST", "Malformed request", 400)
    return envelope_error("ERR_INVALID_REQUEST", e.description or "Request error",
                          e.code or 400)


@app.errorhandler(Exception)
def handle_unexpected(e):
    return envelope_error("ERR_INTERNAL", "Internal server error", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
