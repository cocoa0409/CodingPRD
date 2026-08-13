"""Forging Plant API — entry point. Flask app, error handlers, route registration."""
import os

from flask import Flask

from core import ApiError, error_body, err
import routes_core
import routes_ops
import routes_quality

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error_body(e)


@app.errorhandler(404)
def _handle_404(e):
    return error_body(err("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(405)
def _handle_405(e):
    return error_body(err("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(Exception)
def _handle_generic(e):
    if isinstance(e, ApiError):
        return error_body(e)
    return error_body(err("ERR_INTERNAL", 500, f"internal error: {e}"))


routes_core.register(app)
routes_ops.register(app)
routes_quality.register(app)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
