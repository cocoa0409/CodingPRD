"""Portfolio Asset Management API — Flask entry point.

Boots an empty in-memory store (no seeding) and serves the full API surface
under /api on 0.0.0.0:$PORT (default 10000).
"""
import os
from flask import Flask

from core import ApiError, error_response
import routes_a
import routes_b
import routes_c
import routes_d

app = Flask(__name__)
app.url_map.strict_slashes = False

for bp in (routes_a.bp, routes_b.bp, routes_c.bp, routes_d.bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _handle_404(_err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def _handle_405(_err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(Exception)
def _handle_unexpected(err):
    return error_response(ApiError("ERR_INTERNAL", 500, f"Internal error: {err}"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
