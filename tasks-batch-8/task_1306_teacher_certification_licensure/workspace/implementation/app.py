"""Entry point: Flask app, error handlers, route registration."""
import os

from flask import Flask

import errors
import routes_core
import routes_license
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_license.bp)


@app.errorhandler(errors.ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, errors.ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_VALIDATION", "Unexpected error: %s" % str(e), 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
