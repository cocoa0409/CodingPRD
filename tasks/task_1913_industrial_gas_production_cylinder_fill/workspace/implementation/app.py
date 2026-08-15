"""Industrial Gas Cylinder Fill API — Flask entry point.

In-memory storage only; nothing is seeded at startup. Every entity is created
through the declared API surface. Reads $PORT (default 10000), binds 0.0.0.0.
"""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from response import error as error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

from routes import analyses, billing, blends, core_ops, customers, cylinders, drivers, fill_lots, installations, rentals  # noqa: E402

for module in (core_ops, cylinders, fill_lots, analyses, customers, rentals, drivers, installations, blends, billing):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.status, exc.message)


@app.errorhandler(404)
def handle_404(exc):
    return error_response(ERR_NOT_FOUND, 404, "resource not found")


@app.errorhandler(405)
def handle_405(exc):
    return error_response(ERR_NOT_FOUND, 405, "method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return error_response(exc.error_id, exc.status, exc.message)
    return error_response("ERR_INTERNAL", 500, str(exc))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
