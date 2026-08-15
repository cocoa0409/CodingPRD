"""Entry point: Flask app, error handlers, blueprint registration."""
import os
import traceback

from flask import Flask
from werkzeug.exceptions import HTTPException

from envelope import error_response
from errors import ApiError, ERR_NOT_FOUND
from routes import bp

app = Flask(__name__)
app.url_map.strict_slashes = False
app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(HTTPException)
def handle_http_exception(err):
    # Unmatched routes and wrong methods surface as ERR_NOT_FOUND in the
    # standard envelope.
    return error_response(ERR_NOT_FOUND, err.code or 404,
                          err.description or "not found")


@app.errorhandler(Exception)
def handle_unexpected(err):
    traceback.print_exc()
    return error_response("ERR_INTERNAL", 500, str(err))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
