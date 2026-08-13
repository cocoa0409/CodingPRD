"""Livestock Transport & Hauling API — Flask entry point."""
import os

from flask import Flask

from errors import ApiError
from middleware import authenticate
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.before_request
def _auth():
    if request_path_is_api():
        authenticate()


def request_path_is_api():
    from flask import request
    return request.path.startswith("/haul")


# ---------------------------------------------------------------- blueprints
import routes_admin
import routes_trailers
import routes_loads
import routes_papers
import routes_ops
import routes_incidents
import routes_settlements
import routes_clock

for mod in (routes_admin, routes_trailers, routes_loads, routes_papers,
            routes_ops, routes_incidents, routes_settlements, routes_clock):
    app.register_blueprint(mod.bp)


# ---------------------------------------------------------------- errors
@app.errorhandler(ApiError)
def _api_error(err):
    return error_response(err)


@app.errorhandler(404)
def _not_found(_err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(405)
def _method_not_allowed(_err):
    return error_response(ApiError("ERR_METHOD_NOT_ALLOWED", 405, "method not allowed"))


@app.errorhandler(Exception)
def _internal(err):
    return error_response(ApiError("ERR_INTERNAL", 500, str(err)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
