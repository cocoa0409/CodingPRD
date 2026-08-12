import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import ALL_BLUEPRINTS

app = Flask(__name__)

for bp in ALL_BLUEPRINTS:
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.status, err.message)


@app.errorhandler(404)
def handle_not_found(err):
    return error_response("ERR_NOT_FOUND", 404, "Path id does not resolve")


@app.errorhandler(405)
def handle_method_not_allowed(err):
    return error_response("ERR_NOT_FOUND", 404, "Path does not resolve for this method")


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, HTTPException):
        return error_response("ERR_INVALID_REQUEST", err.code or 400,
                              err.description or "Request error")
    return error_response("ERR_INVALID_REQUEST", 500, str(err))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
