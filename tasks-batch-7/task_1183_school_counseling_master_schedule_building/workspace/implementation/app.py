"""Entry point: Flask app, error handlers, blueprint registration."""

import os

from flask import Flask

from envelope import error_response
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST

app = Flask(__name__)

from routes import terms, catalog, people, requests, sections, changes, \
    appointments, recovery, reads

for module in (terms, catalog, people, requests, sections, changes,
               appointments, recovery, reads):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ERR_NOT_FOUND, 404, "Resource does not exist")


@app.errorhandler(405)
def handle_405(err):
    return error_response(ERR_NOT_FOUND, 404, "Resource does not exist")


@app.errorhandler(400)
def handle_400(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.http_status, err.message)
    return error_response(ERR_INVALID_REQUEST, 400, "Malformed request")


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response("ERR_INTERNAL", 500, "Internal server error")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
