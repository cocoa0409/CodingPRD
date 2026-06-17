"""K-12 Field Trip & Permission Management API.

Entry point, error handlers, and all route registration. Storage is fully
in-memory and starts empty on every boot (db.py). No entity is ever seeded.
"""
import os

from flask import Flask

from errors import ApiError, ERROR_HTTP
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

# Register all route blueprints.
from routes import register_routes  # noqa: E402
register_routes(app)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    # Unknown route — not a domain not-found. Use the generic envelope.
    return error_response("ERR_VALIDATION", 422, "Unknown route or method.")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_VALIDATION", 422, "Method not allowed.")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.http_status, e.message)
    return error_response("ERR_VALIDATION", 422, "Unexpected error: " + str(e))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Prefer a production-grade WSGI server (waitress) over Werkzeug's dev
    # server: under the benchmark's per-test-server isolation the process is
    # rebooted before every test and, with many rounds running concurrently,
    # the single-process dev server can drop connections (BadStatusLine) under
    # peak CPU contention. Waitress' threaded connection handling is robust to
    # that load. Fall back to the threaded dev server if waitress is absent.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=16,
              connection_limit=1000, channel_timeout=120)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
