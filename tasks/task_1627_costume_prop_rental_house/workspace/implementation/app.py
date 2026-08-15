"""Costume & Prop Rental House API — Flask entry point.

Storage is in-memory only (Python dicts). The store boots empty on every
process start; no entity is ever seeded or preloaded.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response
import routes_a
import routes_b
import routes_c

app = Flask(__name__)
app.register_blueprint(routes_a.bp)
app.register_blueprint(routes_b.bp)
app.register_blueprint(routes_c.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(err):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(err):
    return error_response("ERR_NOT_FOUND", 405, "Method not allowed")


@app.errorhandler(500)
def handle_500(err):
    return error_response("ERR_VALIDATION", 500, "Internal server error")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
