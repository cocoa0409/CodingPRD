"""Neighborhood Infrastructure Petition & Assessment Program API.

Flask entry point: registers blueprints, maps ApiError to the error envelope,
and serves 0.0.0.0:$PORT (default 10000) in the foreground.
"""
import os

from flask import Flask

from envelope import error_response
from errors import ApiError
import routes_assessments
import routes_clock
import routes_construction
import routes_districts
import routes_estimates
import routes_hearings
import routes_owners
import routes_petitions
import routes_resolutions

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (
    routes_clock,
    routes_districts,
    routes_owners,
    routes_petitions,
    routes_estimates,
    routes_hearings,
    routes_resolutions,
    routes_construction,
    routes_assessments,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_response("ERR_METHOD_NOT_ALLOWED", 405, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(err):
    return error_response("ERR_INTERNAL", 500, str(err))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
