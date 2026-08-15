"""Traffic Calming Request & Neighborhood Speed Study API — entry point.

In-memory store, logical clock booting at 2026-08-01T00:00:00Z, no seeding.
Binds 0.0.0.0:$PORT (default 10000) per INSTRUCTION.md.
"""
import os

from flask import Flask

from envelope import error_response, raw_object_response
from errors import ApiError
from routes import ALL_BLUEPRINTS

app = Flask(__name__)

for bp in ALL_BLUEPRINTS:
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_routing_404(err):
    return error_response(ApiError(404, "ERR_NOT_FOUND", "Resource not found"))


@app.errorhandler(405)
def handle_routing_405(err):
    return error_response(ApiError(405, "ERR_METHOD_NOT_ALLOWED", "Method not allowed"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    app.logger.exception("unexpected error")
    return error_response(ApiError(500, "ERR_INTERNAL", "Internal server error"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
