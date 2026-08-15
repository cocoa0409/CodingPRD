"""Flask entry point: route registration + error handlers."""

import os
from flask import Flask

from errors import ApiError, err, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return error_response(err(ERR_NOT_FOUND, "Resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return error_response(err(ERR_NOT_FOUND, "Method not allowed"))


@app.errorhandler(400)
def handle_400(e):
    return error_response(err(ERR_INVALID_REQUEST, "Bad request"))


@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, ApiError):
        return error_response(e)
    app.logger.exception("Unhandled exception")
    return error_response(err(ERR_INVALID_REQUEST, str(e)))


# Register all routes
import routes  # noqa: E402, F401


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
