import os

from flask import Flask

from errors import ApiError
from envelope import error_response
from routes import register_routes

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_not_found(e):
    return error_response("ERR_INVALID_REQUEST", "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return error_response("ERR_INVALID_REQUEST", "Method not allowed", 405)


@app.errorhandler(500)
def handle_internal(e):
    return error_response("ERR_INVALID_REQUEST", "Internal server error", 500)


register_routes(app)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
