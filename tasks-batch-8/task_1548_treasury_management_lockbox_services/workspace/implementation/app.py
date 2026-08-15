"""Entry point: Flask app, error handlers, route registration."""
import os
import traceback

from flask import Flask

from appobj import api
from util import ApiError, err_body

import routes_admin  # noqa: F401
import routes_sites  # noqa: F401
import routes_batches  # noqa: F401
import routes_billing  # noqa: F401
import routes_flat  # noqa: F401

app = Flask(__name__)
app.url_map.strict_slashes = False
app.register_blueprint(api)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return err_body(e)


@app.errorhandler(404)
def handle_404(e):
    return err_body(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return err_body(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(Exception)
def handle_generic(e):
    traceback.print_exc()
    return err_body(ApiError("ERR_INVALID_REQUEST", 400, str(e)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
