"""Equine Rescue & Sanctuary Operations API — entry point."""

import os

from flask import Flask

from errors import ApiError
from response import error_body, ok_object
from routes import (
    clock_routes,
    horses,
    quarantine,
    rehab,
    housing,
    adoption,
    sponsorship,
    feed,
    volunteers,
    euthanasia,
)

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (
    clock_routes,
    horses,
    quarantine,
    rehab,
    housing,
    adoption,
    sponsorship,
    feed,
    volunteers,
    euthanasia,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_body(err)


class _NotFound(ApiError):
    def __init__(self):
        super().__init__("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(404)
def handle_404(_err):
    return error_body(_NotFound())


@app.errorhandler(405)
def handle_405(_err):
    return error_body(_NotFound())


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_body(err)
    wrapped = ApiError("ERR_INTERNAL", 500, str(err))
    return error_body(wrapped)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
