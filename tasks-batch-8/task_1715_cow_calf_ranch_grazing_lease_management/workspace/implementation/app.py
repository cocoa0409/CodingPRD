"""Entry point: Flask app, error handlers, blueprint registration.

Boots cleanly from a fresh process with an EMPTY store (no seeding).
Listens on PORT (default 10000), bound to 0.0.0.0, foreground.
"""
import os

from flask import Flask, jsonify

from core import ApiError, error_envelope
import routes_core
import routes_livestock

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_livestock.bp)


@app.errorhandler(ApiError)
def handle_api_error(e: ApiError):
    body, status = error_envelope(e.error_id, e.message, e.http_status)
    return jsonify(body), status


@app.errorhandler(404)
def handle_404(e):
    body, status = error_envelope("ERR_NOT_FOUND", "Resource not found", 404)
    return jsonify(body), status


@app.errorhandler(405)
def handle_405(e):
    body, status = error_envelope("ERR_NOT_FOUND", "Method not allowed", 404)
    return jsonify(body), status


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        body, status = error_envelope(e.error_id, e.message, e.http_status)
        return jsonify(body), status
    body, status = error_envelope("ERR_INVALID_REQUEST", f"Unexpected error: {e}", 400)
    return jsonify(body), status


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
