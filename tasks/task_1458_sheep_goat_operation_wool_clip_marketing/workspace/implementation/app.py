"""Entry point: app factory, error handlers, route registration."""
import os
import traceback

from flask import Flask

import response
from errors import ApiError, ERR_INTERNAL, ERR_NOT_FOUND, ERR_VALIDATION
from middleware import before_request_auth
from routes import register_all

app = Flask(__name__)
app.url_map.strict_slashes = False

app.before_request(before_request_auth)
register_all(app)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return response.error(err.error_id, err.status, err.message)


@app.errorhandler(404)
def handle_not_found(_err):
    return response.error(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "resource not found")


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return response.error(ERR_VALIDATION[0], 405, "method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(err):
    traceback.print_exc()
    return response.error(ERR_INTERNAL[0], ERR_INTERNAL[1], "internal server error")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
