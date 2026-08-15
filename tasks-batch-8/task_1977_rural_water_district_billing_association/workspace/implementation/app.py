"""Entry point: Flask app, error handlers, route registration.

Storage is in-memory only and starts empty on every boot. All timestamps read
from the server-side logical clock (default 2026-08-01T00:00:00Z).
"""
import os

from flask import Flask

from errors import ApiError
from response import err

app = Flask(__name__)
app.url_map.strict_slashes = False

from routes import billing, core, governance, petitions, reverse, safety, taps  # noqa: E402

for bp in (core.bp, taps.bp, billing.bp, governance.bp, petitions.bp, safety.bp, reverse.bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return err("ERR_NOT_FOUND", 404, "The requested resource does not exist")


@app.errorhandler(405)
def handle_405(e):
    return err("ERR_NOT_FOUND", 405, "Method not allowed for this path")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return err(e.error_id, e.http_status, e.message)
    return err("ERR_INVALID_REQUEST", 400, "Malformed request")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
