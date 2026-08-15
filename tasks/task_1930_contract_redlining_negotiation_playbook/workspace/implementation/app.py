"""Contract Redlining Playbook API — Flask entry point.

Storage is in-memory only (module-level dicts). The store starts empty on
every boot; nothing is seeded at startup.
"""
import os

from flask import Flask

from core import ApiError, error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

import routes_a
import routes_b
import routes_c

app.register_blueprint(routes_a.bp)
app.register_blueprint(routes_b.bp)
app.register_blueprint(routes_c.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found.")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found.")


@app.errorhandler(Exception)
def handle_generic(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.status, e.message)
    return error_response("ERR_INTERNAL", 500, "Internal server error: %s" % e)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
