"""Entry point: Flask app wiring, error handlers, route registration."""
import os

from flask import Flask

from core import ApiError, err_body
from routes import bp

app = Flask(__name__)
app.url_map.strict_slashes = False
app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_body(e)


@app.errorhandler(404)
def handle_not_found(e):
    return err_body(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return err_body(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return err_body(e)
    return err_body(ApiError("ERR_INTERNAL", 500, str(e)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
