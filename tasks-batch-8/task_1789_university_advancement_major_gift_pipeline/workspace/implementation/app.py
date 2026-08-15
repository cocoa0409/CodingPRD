"""Entry point: Flask app, error handlers, route registration.

The store starts empty on every boot — nothing is seeded at startup; all
entities are constructed through the declared API surface.
"""

import os

from flask import Flask

from core import error_body
from errors import ApiError, ERR_RESOURCE_NOT_FOUND, ERR_INVALID_REQUEST
from routes import ALL_BLUEPRINTS

app = Flask(__name__)
app.url_map.strict_slashes = False

for bp in ALL_BLUEPRINTS:
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_body(err.error_id, err.message), err.status


@app.errorhandler(404)
def handle_not_found(err):
    return error_body(ERR_RESOURCE_NOT_FOUND, "Resource not found"), 404


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return error_body(ERR_INVALID_REQUEST, "Method not allowed for this resource"), 400


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_body(err.error_id, err.message), err.status
    return error_body(ERR_INVALID_REQUEST, f"Unexpected error: {err}"), 400


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
