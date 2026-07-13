"""Vacant & Abandoned Property Registry API — Flask entry point."""
import os

from flask import Flask

from envelope import ApiError, error_response
import routes_core
import routes_enf

# static_folder=None so Flask does not register an extra /static/<path> rule;
# the app then exposes exactly the 38 declared endpoints.
app = Flask(__name__, static_folder=None)
app.url_map.strict_slashes = False

routes_core.register(app)
routes_enf.register(app)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(_e):
    return error_response(ApiError("ERR_PROPERTY_NOT_FOUND", "resource not found"))


@app.errorhandler(405)
def handle_405(_e):
    return error_response(ApiError("ERR_UNAUTHORIZED", "method not allowed"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_VALIDATION", "unexpected error: %s" % err))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
