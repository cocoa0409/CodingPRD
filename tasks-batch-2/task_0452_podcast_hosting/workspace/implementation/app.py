"""Podcast Hosting & Monetization API — Flask entry point.

Wires every endpoint from PRD §4 / SCAFFOLD §1.5, registers the global error
handler that emits the standard error envelope (PRD §2.2), and runs the server in
the foreground on 0.0.0.0:$PORT (default 10000).

All state is in-memory and starts empty on every boot (db.py). Nothing is seeded.
"""

import os

from flask import Flask

import errors
import response
from middleware import authenticate

app = Flask(__name__)
app.url_map.strict_slashes = False

# Register route groups. Each module attaches its routes to `app`.
import routes_actors      # noqa: E402
import routes_shows       # noqa: E402
import routes_episodes    # noqa: E402
import routes_media       # noqa: E402
import routes_feeds       # noqa: E402
import routes_subscriptions  # noqa: E402
import routes_distributions  # noqa: E402
import routes_campaigns   # noqa: E402
import routes_placements  # noqa: E402
import routes_downloads   # noqa: E402
import routes_payouts     # noqa: E402
import routes_clock       # noqa: E402

routes_clock.register(app)
routes_actors.register(app)
routes_shows.register(app)
routes_episodes.register(app)
routes_media.register(app)
routes_feeds.register(app)
routes_subscriptions.register(app)
routes_distributions.register(app)
routes_campaigns.register(app)
routes_placements.register(app)
routes_downloads.register(app)
routes_payouts.register(app)


@app.errorhandler(errors.ApiError)
def handle_api_error(exc):
    body = response.error_response(exc.error_id, exc.message)
    return body, exc.http_status


@app.errorhandler(404)
def handle_404(exc):
    # Unknown route -> ERR_NOT_FOUND envelope (PRD §5).
    body = response.error_response("ERR_NOT_FOUND", "Resource not found")
    return body, 404


@app.errorhandler(405)
def handle_405(exc):
    body = response.error_response("ERR_NOT_FOUND", "Method not allowed")
    return body, 404


@app.errorhandler(400)
def handle_400(exc):
    # Malformed JSON body etc. (PRD §2.5 -> ERR_INVALID_REQUEST).
    body = response.error_response("ERR_INVALID_REQUEST", "Malformed request")
    return body, 400


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, errors.ApiError):
        return handle_api_error(exc)
    body = response.error_response("ERR_INVALID_REQUEST", "Unexpected error: " + str(exc))
    return body, 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Serve via waitress (a production WSGI server with a proper accept loop and
    # worker pool). Under the benchmark's 8× concurrent per-test-server restarts,
    # Flask's dev server can drop connections mid-response (BadStatusLine); waitress
    # handles connection setup/teardown robustly. Fall back to the dev server only if
    # waitress is unavailable.
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
